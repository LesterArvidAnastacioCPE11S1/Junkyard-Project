# inbox_routes.py - HTTP endpoints for the inbox and for the SMS / Messenger webhooks.
import hmac
import json
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend import inbox_db
from backend.channel_parsers import (
    normalize_sms_payload,
    parse_messenger_payload,
    verify_messenger_signature,
)
from backend.inbox_service import ingest_message

router = APIRouter()

Channel = Literal["sms", "email", "messenger", "manual"]
Intent = Literal["Price_Inquiry", "Pickup_Request", "Bulk_Negotiation", "Other"]
Material = Literal["Plastic", "Paper", "Cardboard", "Aluminum",
                   "Other_Metals", "Glass", "Electronic_Waste", "Unknown"]


def require_key(x_api_key: Optional[str] = Header(default=None)):
    """If INGEST_KEY is set, callers must send it in an X-API-Key header."""
    expected = os.environ.get("INGEST_KEY")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


class InboundMessage(BaseModel):
    channel: Channel = "manual"
    sender: str = Field(default="unknown", max_length=200)
    text: str = Field(min_length=1, max_length=5000)
    subject: Optional[str] = Field(default=None, max_length=300)
    external_id: Optional[str] = Field(default=None, max_length=300)
    received_at: Optional[str] = None


class ReviewRequest(BaseModel):
    intent: Optional[Intent] = None            # leave empty to confirm the prediction
    materials: Optional[list[Material]] = None


#  inbox
@router.post("/inbox/ingest", status_code=201)
def ingest(msg: InboundMessage, response: Response, _=Depends(require_key)):
    """Classify and store one message from any channel."""
    record, created = ingest_message(
        msg.channel, msg.sender, msg.text,
        external_id=msg.external_id, received_at=msg.received_at, subject=msg.subject,
    )
    if not created:
        response.status_code = 200   # already stored (duplicate delivery)
    return {"created": created, "message": record}


@router.get("/inbox")
def list_inbox(
    channel: Optional[Channel] = None,
    intent: Optional[Intent] = None,
    needs_review: Optional[bool] = None,
    status: Optional[Literal["new", "confirmed", "corrected"]] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_key),
):
    """Newest first. `intent` matches the operator's correction when there is one."""
    return {"messages": inbox_db.list_messages(channel, intent, needs_review, status, limit, offset)}


@router.get("/inbox/stats")           # must stay above /inbox/{message_id}
def inbox_stats(_=Depends(require_key)):
    return inbox_db.stats()


@router.get("/inbox/{message_id}")
def get_inbox_message(message_id: int, _=Depends(require_key)):
    record = inbox_db.get_message(message_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return record


@router.patch("/inbox/{message_id}/review")
def review(message_id: int, body: ReviewRequest, _=Depends(require_key)):
    """Operator confirms or corrects the labels (the corrections become training data)."""
    record = inbox_db.review_message(message_id, body.intent, body.materials)
    if record is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return record


# SMS webhook
@router.post("/webhooks/sms", status_code=201)
async def sms_webhook(request: Request, _=Depends(require_key)):
    """For an SMS-forwarder app or SMS gateway that POSTs JSON like
    {"sender": "+63917...", "text": "message"}."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    try:
        parsed = normalize_sms_payload(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    record, created = await run_in_threadpool(ingest_message, "sms", **parsed)
    return {"created": created, "message": record}


#  Messenger webhook
@router.get("/webhooks/messenger", response_class=PlainTextResponse)
def messenger_verify(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Meta calls this once when you register the webhook."""
    expected = os.environ.get("FB_VERIFY_TOKEN")
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
        return challenge or ""
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/messenger", response_class=PlainTextResponse)
async def messenger_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    raw = await request.body()
    if not verify_messenger_signature(raw, x_hub_signature_256, os.environ.get("FB_APP_SECRET")):
        raise HTTPException(status_code=403, detail="Bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON")

    for item in parse_messenger_payload(payload):
        await run_in_threadpool(ingest_message, "messenger", **item)
    return "EVENT_RECEIVED"        # Meta expects a quick 200