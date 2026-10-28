# price_updates.py - ties the forecast, the opt-in list and the reply system together.
#   handle_incoming()  a customer message arrived: was it a YES / NO / STOP to our invitation?
#   send_forecast()    a staff member sends the forecast - to subscribed customers ONLY.
import re
from datetime import datetime, timedelta, timezone

from backend import accounts_db, inbox_db, reply_service
from backend.channel_parsers import clean_email_body
from backend.errors import ApiError
from Prices import forecast, subscriptions

PH = timezone(timedelta(hours=8))

SUBSCRIBED_TEXT = ("Salamat! You're now subscribed to {shop} price updates. We'll send our expected "
                   "buying prices from time to time. Reply STOP anytime to unsubscribe.")
UNSUBSCRIBED_TEXT = ("You've been unsubscribed from {shop} price updates and won't get any more. "
                     "You can still message us anytime to ask for prices.")


_NOTES = {"subscribed": "Subscribed to price updates", "declined": "Declined price updates",
          "unsubscribed": "Unsubscribed from price updates"}


def _shop_name(shop_id):
    return (accounts_db.get_shop(shop_id) or {}).get("name") or "ScrapDesk"


def _typed_answer(record):
    """What the customer actually typed: no subject line and no quoted copy of our own message."""
    text = (record.get("text") or "").strip()
    subject = (record.get("subject") or "").strip()
    if subject and text.lower().startswith(subject.lower()):
        text = text[len(subject):].strip()                  # emails are stored as "subject\nbody"
    if record.get("channel") == "email":
        text = clean_email_body(text)                       # drops "On ... wrote:" and "> quoted" lines
    return text


# a customer answered (or said STOP)
def handle_incoming(shop_id, record):
    """Called for every new customer message. Returns what happened, or None when the message had
    nothing to do with price updates (the common case, and then nothing at all changes)."""
    address = inbox_db.get_reply_address(shop_id, record["id"])
    if not address:
        return None
    result = subscriptions.apply_answer(shop_id, record["channel"], address, _typed_answer(record), record["id"])
    if result is None:
        return None

    inbox_db.mark_handled(shop_id, record["id"], _NOTES.get(result["action"]))   # not something staff need to review

    template = {"subscribed": SUBSCRIBED_TEXT, "unsubscribed": UNSUBSCRIBED_TEXT}.get(result["action"])
    if template:                                          # a "no" gets no extra message
        body = template.format(shop=_shop_name(shop_id))
        try:
            reply_service.deliver(shop_id, record["channel"], address, f"{_shop_name(shop_id)} price updates",
                                  body, message=record)
            inbox_db.add_reply(shop_id, record["id"], record["channel"], record.get("reply_hint"), None, body,
                               "sent", None, None)
        except RuntimeError as error:                     # the choice is still saved; staff can see the failure
            inbox_db.add_reply(shop_id, record["id"], record["channel"], record.get("reply_hint"), None, body,
                               "failed", str(error), None)
    return result


# the forecast, to the people who said yes
def preview(shop_id):
    result = forecast.forecast_shop(shop_id)
    return {**result,
            "message": forecast.compose_message(_shop_name(shop_id), result),
            "subscribers": subscriptions.counts(shop_id)}


def _sent_today(sub):
    if not sub["last_sent_at"]:
        return False
    sent = datetime.fromisoformat(sub["last_sent_at"]).astimezone(PH).date()
    return sent == datetime.now(PH).date()


def send_forecast(shop_id, user, text=None, include_already_sent=False):
    body = (text if text is not None else preview(shop_id)["message"]).strip()
    if not body:
        raise ApiError(422, "There is nothing to send yet. Set buying prices in Price list first.")
    if "stop" not in body.lower():
        body += "\nReply STOP to unsubscribe."
    if len(body) > reply_service.MAX_REPLY_CHARS:
        raise ApiError(422, f"Messages are limited to {reply_service.MAX_REPLY_CHARS} characters.")

    subscribers = subscriptions.list_subscribers(shop_id, "subscribed")     # the ONLY audience
    if not subscribers:
        raise ApiError(409, "No customers have agreed to price updates yet. Offer it in a price reply first.")

    subject = f"{_shop_name(shop_id)} price update"
    delivered, failed, skipped, failures = 0, 0, 0, []
    for sub in subscribers:
        if not include_already_sent and _sent_today(sub):
            skipped += 1
            continue
        try:
            reply_service.deliver(shop_id, sub["channel"], sub["address"], subject, body)
            subscriptions.mark_sent(sub["id"])
            delivered += 1
        except RuntimeError as error:
            subscriptions.mark_sent(sub["id"], str(error))
            failed += 1
            failures.append({"to": inbox_db.mask_address(sub["address"]), "channel": sub["channel"],
                             "reason": str(error)})
    if delivered or failed:
        subscriptions.log_run(shop_id, user["id"], delivered + failed, delivered, failed, body)
    return {"delivered": delivered, "failed": failed, "skipped_already_sent": skipped, "failures": failures}


# what the staff screen shows
def _display_name(name, address):
    """A person's name, or None when the stored 'name' is really just their phone number / email / id."""
    name = (name or "").strip()
    if not name or subscriptions.normalize_address(name) == address or "@" in name:
        return None
    if re.fullmatch(r"[+\d\s\-().]{6,}", name) or re.fullmatch(r"\d{8,}", name):
        return None
    return name


def public_subscribers(shop_id):
    out = []
    for s in subscriptions.list_subscribers(shop_id):
        out.append({"id": s["id"], "name": _display_name(s["name"], s["address"]), "channel": s["channel"],
                    "to_hint": inbox_db.mask_address(s["address"]), "status": s["status"],
                    "invited_at": s["invited_at"], "responded_at": s["responded_at"],
                    "last_sent_at": s["last_sent_at"], "last_error": s["last_error"],
                    "consent_text": s["consent_text"]})
    return out
