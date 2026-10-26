# channel_routes.py - email, SMS, Twilio, and Facebook Messenger routes.

import hmac
import json
import os
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend import accounts_db, channel_service, email_service, security
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
    imap_host: str = Field(
        default="imap.gmail.com",
        max_length=200,
    )
    imap_user: str = Field(
        min_length=3,
        max_length=200,
    )
    imap_password: str = Field(
        min_length=1,
        max_length=200,
    )
    folder: str = Field(
        default="INBOX",
        max_length=100,
    )
    smtp_host: Optional[str] = Field(      # for sending replies; empty = worked out from the IMAP server
        default=None,
        max_length=200,
    )


class MessengerConnectRequest(BaseModel):
    page_id: str = Field(
        min_length=3,
        max_length=100,
    )
    page_access_token: Optional[str] = Field(   # needed to reply to customers on Messenger
        default=None,
        max_length=1000,
    )


class TwilioSMSConnectRequest(BaseModel):
    account_sid: str = Field(
        min_length=34,
        max_length=34,
    )
    auth_token: str = Field(
        min_length=1,
        max_length=200,
    )
    phone_number: str = Field(
        min_length=9,
        max_length=16,
    )


# ---------------------------------------------------------------------
# CHANNEL SETTINGS
# ---------------------------------------------------------------------

@router.get("/channels")
def channel_status(owner: dict = Depends(owner_only)):
    """Return this shop's channel status without returning secrets."""
    return channel_service.get_status(owner["shop_id"])


# ---------------------------------------------------------------------
# EMAIL CONNECTION
# ---------------------------------------------------------------------

@router.put("/channels/email")
def connect_email(
    body: EmailConnectRequest,
    owner: dict = Depends(owner_only),
):
    channel_service.set_email(
        owner["shop_id"],
        body.imap_host,
        body.imap_user,
        body.imap_password,
        body.folder,
        body.smtp_host,
    )

    return channel_service.get_status(owner["shop_id"])["email"]


@router.delete("/channels/email")
def disconnect_email(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "email")
    return {"ok": True}


@router.post("/channels/email/poll-now")
def poll_email_now(user: dict = Depends(inbox_staff)):
    """Check the connected mailbox immediately."""
    return email_service.poll_shop(user["shop_id"])


# ---------------------------------------------------------------------
# SMS PHONE-FORWARDING CONNECTION
# ---------------------------------------------------------------------

@router.post("/channels/sms/key")
def create_sms_key(owner: dict = Depends(owner_only)):
    """Create or replace the key used by a phone-forwarding app."""
    key = channel_service.regenerate_sms_key(owner["shop_id"])

    return {
        "sms_key": key,
        "webhook_path": f"/webhooks/sms/{owner['shop_id']}",
        "note": (
            "Copy this key now. Send it in an X-API-Key header "
            "(or ?key=...) from the forwarding app."
        ),
    }


@router.delete("/channels/sms")
def disable_sms(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "sms")
    return {"ok": True}


# ---------------------------------------------------------------------
# SMS TWILIO CONNECTION
# ---------------------------------------------------------------------

@router.put("/channels/sms/twilio")
def connect_twilio_sms(
    body: TwilioSMSConnectRequest,
    owner: dict = Depends(owner_only),
):
    """Save Twilio configuration for this shop."""
    channel_service.set_twilio_sms(
        owner["shop_id"],
        body.account_sid,
        body.auth_token,
        body.phone_number,
    )

    return channel_service.get_status(owner["shop_id"])["sms_twilio"]


@router.delete("/channels/sms/twilio")
def disconnect_twilio_sms(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "sms_twilio")
    return {"ok": True}


# ---------------------------------------------------------------------
# FACEBOOK MESSENGER CONNECTION
# ---------------------------------------------------------------------

@router.put("/channels/messenger")
def connect_messenger(
    body: MessengerConnectRequest,
    owner: dict = Depends(owner_only),
):
    channel_service.set_messenger(
        owner["shop_id"],
        body.page_id,
        body.page_access_token,
    )

    return channel_service.get_status(owner["shop_id"])["messenger"]


@router.delete("/channels/messenger")
def disconnect_messenger(owner: dict = Depends(owner_only)):
    channel_service.remove(owner["shop_id"], "messenger")
    return {"ok": True}


# ---------------------------------------------------------------------
# SMS PHONE-FORWARDING WEBHOOK
# ---------------------------------------------------------------------

@router.post("/webhooks/sms/{shop_id}", status_code=201)
async def sms_webhook(
    shop_id: int,
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    key: Optional[str] = Query(default=None),
):
    """
    Receive JSON sent by a phone SMS-forwarding app.

    Example JSON:
        {
            "sender": "+639171234567",
            "text": "Magkano po ang karton?"
        }
    """
    valid_key = await run_in_threadpool(
        channel_service.verify_sms_key,
        shop_id,
        x_api_key or key,
    )

    if not valid_key:
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

    record, created = await run_in_threadpool(
        ingest_message,
        shop_id,
        "sms",
        **parsed,
    )

    return {
        "created": created,
        "message": record,
    }


# ---------------------------------------------------------------------
# TWILIO INCOMING SMS WEBHOOK
# ---------------------------------------------------------------------

@router.post(
    "/webhooks/twilio/sms",
    response_class=PlainTextResponse,
)
async def twilio_sms_webhook(request: Request):
    """
    Receive an incoming SMS from Twilio.

    Configure this endpoint in Twilio as an incoming-message webhook
    using HTTP POST. The server must be publicly reachable over HTTPS.
    """
    from twilio.request_validator import RequestValidator

    raw = await request.body()

    try:
        decoded = raw.decode("utf-8")
        parsed_form = parse_qs(
            decoded,
            keep_blank_values=True,
        )
        params = {
            key: values[-1]
            for key, values in parsed_form.items()
            if values
        }
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "Invalid Twilio form data.")

    phone_number = params.get("To", "").strip()
    sender = params.get("From", "").strip()
    text = params.get("Body", "").strip()
    message_sid = params.get("MessageSid", "").strip()

    if not phone_number or not sender or not text:
        raise ApiError(
            400,
            "Missing required Twilio fields: To, From, or Body.",
        )

    connection = await run_in_threadpool(
        accounts_db.find_connection_by_ref,
        "sms_twilio",
        phone_number,
    )

    if not connection or not connection.get("secret_enc"):
        raise ApiError(
            403,
            "No Twilio connection is configured for this number.",
        )

    try:
        auth_token = security.decrypt_secret(
            connection["secret_enc"]
        )
    except Exception:
        raise ApiError(
            503,
            "Unable to read the saved Twilio credentials.",
        )

    signature = request.headers.get(
        "X-Twilio-Signature",
        "",
    )

    validator = RequestValidator(auth_token)

    # The URL must match the public webhook URL Twilio calls.
    if not validator.validate(
        str(request.url),
        params,
        signature,
    ):
        raise ApiError(
            403,
            "Twilio signature verification failed.",
        )

    await run_in_threadpool(
        ingest_message,
        connection["shop_id"],
        "sms",
        sender,
        text[:4000],
        message_sid or None,
    )

    # Twilio expects a valid TwiML response.
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
        status_code=200,
    )


# ---------------------------------------------------------------------
# FACEBOOK MESSENGER WEBHOOK VERIFICATION
# ---------------------------------------------------------------------

@router.get(
    "/webhooks/messenger",
    response_class=PlainTextResponse,
)
def messenger_verify(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Meta calls this endpoint when registering the webhook."""
    expected = os.environ.get("FB_VERIFY_TOKEN")

    if (
        mode == "subscribe"
        and expected
        and token
        and hmac.compare_digest(token, expected)
    ):
        return challenge or ""

    raise ApiError(403, "Verification failed.")


# ---------------------------------------------------------------------
# FACEBOOK MESSENGER WEBHOOK
# ---------------------------------------------------------------------

@router.post(
    "/webhooks/messenger",
    response_class=PlainTextResponse,
)
async def messenger_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    raw = await request.body()

    if not verify_messenger_signature(
        raw,
        x_hub_signature_256,
        os.environ.get("FB_APP_SECRET"),
    ):
        raise ApiError(403, "Bad signature.")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise ApiError(400, "Body must be JSON.")

    for item in parse_messenger_payload(payload):
        page_id = item.pop("page_id", None)

        shop_id = await run_in_threadpool(
            channel_service.shop_for_page,
            page_id,
        )

        if shop_id is None:
            # Ignore Pages that are not connected to a shop.
            continue

        await run_in_threadpool(
            ingest_message,
            shop_id,
            "messenger",
            **item,
        )

    return "EVENT_RECEIVED"