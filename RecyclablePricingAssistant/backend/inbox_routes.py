# inbox_routes.py - the logged-in shop's inbox. Only the owner and dispatchers can use it,
# and everyone only ever sees their own shop's messages.
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from backend import inbox_db, reply_service
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


class ReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=reply_service.MAX_REPLY_CHARS)
    subject: Optional[str] = Field(default=None, max_length=300)    # email only; "Re: ..." is added

class DeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)

class ReviewRequest(BaseModel):
    intent: Optional[Intent] = None            # leave empty to confirm the prediction
    materials: Optional[list[Material]] = None


@router.post("/inbox/ingest", status_code=201)
def ingest(msg: InboundMessage, response: Response, user: dict = Depends(inbox_staff)):
    """Developer/testing endpoint (used by backend/simulate_messages.py). The web app no longer has
    an "Add a message" screen: real messages arrive through the connected email, SMS and Messenger."""
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
    shop_id = user["shop_id"]
    root = inbox_db.root_id(shop_id, message_id)         # a follow-up opens the inquiry it belongs to
    if root is None:
        raise ApiError(404, "Message not found.")
    record = inbox_db.get_message(shop_id, root)
    record["followups"] = inbox_db.list_followups(shop_id, root)
    family = [root, *[f["id"] for f in record["followups"]]]
    record["reply"] = reply_service.reply_options(shop_id, record)
    record["replies"] = inbox_db.list_thread_replies(shop_id, family)
    if record["followup_unread"]:                         # they are seeing the answer now; the flag stays in this response
        inbox_db.clear_followup_unread(shop_id, root)
    from Prices import subscriptions
    record["price_updates"] = subscriptions.message_status(user["shop_id"], record)
    return record

@router.post("/inbox/{message_id}/reply", status_code=201)
def reply(message_id: int, body: ReplyRequest, user: dict = Depends(inbox_staff)):
    """Send an answer to the customer over the channel they used (email, SMS or Messenger)."""
    return reply_service.send_reply(user["shop_id"], user, message_id, body.text, body.subject)

@router.post("/inbox/delete")
def delete_many(body: DeleteRequest, user: dict = Depends(inbox_staff)):
    """Delete several inquiries (and the replies sent for them) to keep the inbox tidy."""
    from Operations import services
    return services.delete_inquiries(user["shop_id"], body.ids)


@router.delete("/inbox/{message_id}")
def delete_one(message_id: int, user: dict = Depends(inbox_staff)):
    from Operations import services
    if inbox_db.get_message(user["shop_id"], message_id) is None:
        raise ApiError(404, "Message not found.")
    result = services.delete_inquiries(user["shop_id"], [message_id])
    if result["blocked"]:
        raise ApiError(409, result["blocked"][0]["reason"])
    return result

@router.patch("/inbox/{message_id}/review")
def review(message_id: int, body: ReviewRequest, user: dict = Depends(inbox_staff)):
    """Confirm or correct the labels (the corrections can become training data)."""
    record = inbox_db.review_message(user["shop_id"], message_id, body.intent, body.materials, user["id"])
    if record is None:
        raise ApiError(404, "Message not found.")
    # If the operator re-labelled it as a pickup request, prepare the draft pickup now.
    from Operations import services
    services.auto_draft_if_needed(user["shop_id"], record)
    # ...and if a draft already exists, carry the corrected materials over to it.
    services.sync_draft_materials(user["shop_id"], record)
    return record