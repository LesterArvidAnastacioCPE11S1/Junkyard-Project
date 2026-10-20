# inbox_routes.py - the logged-in shop's inbox. Only the owner and dispatchers can use it,
# and everyone only ever sees their own shop's messages.
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from backend import inbox_db
from backend.auth import inbox_staff
from backend.errors import ApiError
from backend.inbox_service import ingest_message

router = APIRouter()

Channel = Literal["sms", "email", "messenger", "manual"]
Intent = Literal["Price_Inquiry", "Pickup_Request", "Bulk_Negotiation", "Other"]
Material = Literal["Plastic", "Paper", "Cardboard", "Aluminum",
                   "Other_Metals", "Glass", "Electronic_Waste", "Unknown"]


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


@router.post("/inbox/ingest", status_code=201)
def ingest(msg: InboundMessage, response: Response, user: dict = Depends(inbox_staff)):
    """Add a message by hand (for example one taken over the phone), classified like the rest."""
    record, created = ingest_message(
        user["shop_id"], msg.channel, msg.sender, msg.text,
        external_id=msg.external_id, received_at=msg.received_at, subject=msg.subject,
    )
    if not created:
        response.status_code = 200   # already stored (duplicate)
    return {"created": created, "message": record}


@router.get("/inbox")
def list_inbox(
    channel: Optional[Channel] = None,
    intent: Optional[Intent] = None,
    needs_review: Optional[bool] = None,
    status: Optional[Literal["new", "confirmed", "corrected"]] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(inbox_staff),
):
    """Newest first. `intent` matches the operator's correction when there is one."""
    return {"messages": inbox_db.list_messages(
        user["shop_id"], channel, intent, needs_review, status, limit, offset)}


@router.get("/inbox/stats")           # must stay above /inbox/{message_id}
def inbox_stats(user: dict = Depends(inbox_staff)):
    return inbox_db.stats(user["shop_id"])


@router.get("/inbox/{message_id}")
def get_inbox_message(message_id: int, user: dict = Depends(inbox_staff)):
    record = inbox_db.get_message(user["shop_id"], message_id)
    if record is None:
        raise ApiError(404, "Message not found.")
    return record


@router.patch("/inbox/{message_id}/review")
def review(message_id: int, body: ReviewRequest, user: dict = Depends(inbox_staff)):
    """Confirm or correct the labels (the corrections can become training data)."""
    record = inbox_db.review_message(user["shop_id"], message_id, body.intent, body.materials, user["id"])
    if record is None:
        raise ApiError(404, "Message not found.")
    return record
