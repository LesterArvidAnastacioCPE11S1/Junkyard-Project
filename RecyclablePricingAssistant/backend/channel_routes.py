# channel_routes.py - each shop connects its own email / SMS / Messenger, plus the
# public webhooks that phones and Facebook call.
import hmac
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend import channel_service, email_service
from backend.auth import inbox_staff, owner_only
from backend.channel_parsers import (
    normalize_sms_payload,
    parse_messenger_payload,
    verify_messenger_signature,
)
from backend.errors import ApiError
from backend.inbox_service import ingest_message

router = APIRouter()


class EmailConnectRequest(BaseModel):
    imap_host: str = Field(default="imap.gmail.com", max_length=200)
    imap_user: str = Field(min_length=3, max_length=200)
    imap_password: str = Field(min_length=1, max_length=200)
    folder: str = Field(default="INBOX", max_length=100)


class MessengerConnectRequest(BaseModel):
    page_id: str = Field(min_length=3, max_length=100)


#  connection settings (owner)
@router.get("/channels")
def channel_status(owner: dict = Depends(owner_only)):
    """What this shop has connected. Passwords and full keys are never returned."""
    return channel_service.get_status(owner["shop_id"])


@router.put("/channels/email")
def connect_email(body: EmailConnectRequest, owner: dict = Depends(owner_only)):
    """Connect the shop's mailbox. The login is tested first and the password is saved encrypted."""
    channel_service.set_email(owner["shop_id"], body.imap_host, body.imap_user,
                              body.imap_password, body.folder)
    return channel_service.get_status(owner["shop_id"])["email"]


@router.delete("/channels/email")
def disconnect_email(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "email")
    return {"ok": True}


@router.post("/channels/email/poll-now")
def poll_email_now(user: dict = Depends(inbox_staff)):
    """Check the mailbox right now instead of waiting for the next automatic check."""
    return email_service.poll_shop(user["shop_id"])


@router.post("/channels/sms/key")
def create_sms_key(owner: dict = Depends(owner_only)):
    """Create (or replace) the key for this shop's SMS-forwarder app. It is shown only once."""
    key = channel_service.regenerate_sms_key(owner["shop_id"])
    return {
        "sms_key": key,
        "webhook_path": f"/webhooks/sms/{owner['shop_id']}",
        "note": "Copy this key now. Send it in an X-API-Key header (or ?key=...) from the forwarder app.",
    }


@router.delete("/channels/sms")
def disable_sms(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "sms")
    return {"ok": True}


@router.put("/channels/messenger")
def connect_messenger(body: MessengerConnectRequest, owner: dict = Depends(owner_only)):
    """Tell the system which Facebook Page belongs to this shop."""
    channel_service.set_messenger(owner["shop_id"], body.page_id)
    return channel_service.get_status(owner["shop_id"])["messenger"]


@router.delete("/channels/messenger")
def disconnect_messenger(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "messenger")
    return {"ok": True}


#  SMS webhook (called by a phone)
@router.post("/webhooks/sms/{shop_id}", status_code=201)
async def sms_webhook(
    shop_id: int,
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    key: Optional[str] = Query(default=None),
):
    """An SMS-forwarder app POSTs JSON like {"sender": "+63917...", "text": "message"} here.
    The shop's SMS key goes in the X-API-Key header (or ?key= if the app can't set headers)."""
    if not await run_in_threadpool(channel_service.verify_sms_key, shop_id, x_api_key or key):
        raise ApiError(401, "Invalid SMS key.")
    try:
        payload = await request.json()
    except Exception:
        raise ApiError(400, "Body must be JSON.")
    if not isinstance(payload, dict):
        raise ApiError(400, "Body must be a JSON object.")
    try:
        parsed = normalize_sms_payload(payload)
    except ValueError as error:
        raise ApiError(422, str(error))

    record, created = await run_in_threadpool(ingest_message, shop_id, "sms", **parsed)
    return {"created": created, "message": record}


#  Messenger webhook (called by Meta)
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
    raise ApiError(403, "Verification failed.")


@router.post("/webhooks/messenger", response_class=PlainTextResponse)
async def messenger_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    raw = await request.body()
    if not verify_messenger_signature(raw, x_hub_signature_256, os.environ.get("FB_APP_SECRET")):
        raise ApiError(403, "Bad signature.")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise ApiError(400, "Body must be JSON.")

    for item in parse_messenger_payload(payload):
        page_id = item.pop("page_id", None)
        shop_id = await run_in_threadpool(channel_service.shop_for_page, page_id)
        if shop_id is None:
            continue                       # a Page that no shop has connected: ignore it
        await run_in_threadpool(ingest_message, shop_id, "messenger", **item)
    return "EVENT_RECEIVED"                # Meta expects a quick 200
