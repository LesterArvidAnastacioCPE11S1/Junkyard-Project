# update_routes.py - price forecasts and the customers who agreed to receive them.

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend import reply_service
from backend.auth import inbox_staff
from backend.errors import ApiError
from Prices import price_updates, subscriptions

router = APIRouter()


class SendRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=reply_service.MAX_REPLY_CHARS)   # edited message; empty = use the forecast
    include_already_sent: bool = False        # by default someone who already got today's update is skipped


@router.get("/price-updates")
def overview(user: dict = Depends(inbox_staff)):
    """The forecast, the ready-to-send message, who has agreed, and the last few sends."""
    shop_id = user["shop_id"]
    data = price_updates.preview(shop_id)
    data["people"] = price_updates.public_subscribers(shop_id)
    data["recent_runs"] = subscriptions.recent_runs(shop_id)
    data["offer_line"] = subscriptions.OFFER_LINE
    return data


@router.post("/price-updates/send")
def send(body: SendRequest, user: dict = Depends(inbox_staff)):
    """Send the forecast to subscribed customers only."""
    return price_updates.send_forecast(user["shop_id"], user, (body.text or None), body.include_already_sent)


@router.post("/price-updates/subscribers/{subscriber_id}/unsubscribe")
def unsubscribe(subscriber_id: int, user: dict = Depends(inbox_staff)):
    """A customer asked you (outside the app) to stop. They get no further forecasts."""
    if not subscriptions.set_status(user["shop_id"], subscriber_id, "unsubscribed"):
        raise ApiError(404, "Customer not found.")
    return {"unsubscribed": subscriber_id}