# channel_service.py - each shop's own email / SMS / Messenger connections.
import hmac
import re

from backend import accounts_db, email_service, security
from backend.errors import ApiError


def get_status(shop_id: int) -> dict:
    """Return connection status without exposing passwords or full API keys."""
    status = {
        "email": {"connected": False},
        "sms": {
            "enabled": False,
            "webhook_path": f"/webhooks/sms/{shop_id}",
        },
        "sms_twilio": {
            "connected": False,
            "phone_number": "",
            "account_sid": "",
        },
        "messenger": {"connected": False},
    }

    for connection in accounts_db.list_connections(shop_id):
        channel = connection["channel"]
        config = connection["config"]

        if channel == "email":
            status["email"] = {
                "connected": True,
                "imap_host": config.get("imap_host"),
                "imap_user": config.get("imap_user"),
                "folder": config.get("folder", "INBOX"),
                "last_checked_at": connection["last_checked_at"],
                "last_error": connection["last_error"],
            }

        elif channel == "sms":
            status["sms"].update({
                "enabled": True,
                "key_hint": (connection["secret_hint"] or "") + "…",
            })

        elif channel == "sms_twilio":
            status["sms_twilio"] = {
                "connected": True,
                "phone_number": connection["external_ref"] or "",
                "account_sid": config.get("account_sid", ""),
            }

        elif channel == "messenger":
            status["messenger"] = {
                "connected": True,
                "page_id": connection["external_ref"],
            }

    return status


# ---------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------

def set_email(
    shop_id,
    imap_host,
    imap_user,
    imap_password,
    folder="INBOX",
):
    host = (imap_host or "").strip()
    user = (imap_user or "").strip()
    folder = (folder or "INBOX").strip()

    if not host or not user or not imap_password:
        raise ApiError(400, "Enter the IMAP server, email address, and password.")

    # Test the login before saving the connection.
    email_service.test_imap_login(
        host,
        user,
        imap_password,
        folder,
    )

    try:
        encrypted = security.encrypt_secret(imap_password)
    except RuntimeError as error:
        raise ApiError(503, str(error))

    try:
        accounts_db.upsert_connection(
            shop_id,
            "email",
            external_ref=user.lower(),
            config={
                "imap_host": host,
                "imap_user": user,
                "folder": folder,
            },
            secret_enc=encrypted,
        )
    except accounts_db.ChannelRefTaken:
        raise ApiError(
            409,
            "That mailbox is already connected to another shop.",
        )


# ---------------------------------------------------------------------
# SMS PHONE FORWARDING
# ---------------------------------------------------------------------

def regenerate_sms_key(shop_id) -> str:
    """Create or replace the key used by a phone SMS-forwarding app."""
    key = security.new_api_key()

    accounts_db.upsert_connection(
        shop_id,
        "sms",
        secret_hash=security.token_hash(key),
        secret_hint=key[:8],
    )

    # The complete key is returned only once to the owner.
    return key


def verify_sms_key(shop_id: int, key) -> bool:
    connection = accounts_db.get_connection(shop_id, "sms")

    if connection is None or not key:
        security.burn_password_time(key or "")
        return False

    stored_hash = connection["secret_hash"] or ""

    return hmac.compare_digest(
        stored_hash,
        security.token_hash(key),
    )


# ---------------------------------------------------------------------
# SMS TWILIO
# ---------------------------------------------------------------------

def set_twilio_sms(
    shop_id: int,
    account_sid: str,
    auth_token: str,
    phone_number: str,
) -> None:
    """
    Save Twilio details.

    The Auth Token is encrypted before being stored in SQLite.
    The phone number must use international format, such as +14155550123.
    """
    account_sid = (account_sid or "").strip()
    auth_token = (auth_token or "").strip()
    phone_number = (phone_number or "").strip()

    if not re.fullmatch(r"AC[a-fA-F0-9]{32}", account_sid):
        raise ApiError(400, "Enter a valid Twilio Account SID.")

    if not auth_token:
        raise ApiError(400, "Enter your Twilio Auth Token.")

    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone_number):
        raise ApiError(
            400,
            "Enter the Twilio phone number in international format, "
            "for example +14155550123.",
        )

    try:
        encrypted_token = security.encrypt_secret(auth_token)
    except RuntimeError as error:
        raise ApiError(503, str(error))

    try:
        accounts_db.upsert_connection(
            shop_id,
            "sms_twilio",
            external_ref=phone_number,
            config={
                "account_sid": account_sid,
            },
            secret_enc=encrypted_token,
        )
    except accounts_db.ChannelRefTaken:
        raise ApiError(
            409,
            "That Twilio phone number is already connected to another shop.",
        )


# ---------------------------------------------------------------------
# FACEBOOK MESSENGER
# ---------------------------------------------------------------------

def set_messenger(shop_id, page_id):
    page_id = (page_id or "").strip()

    if not page_id:
        raise ApiError(400, "Enter a Facebook Page ID.")

    try:
        accounts_db.upsert_connection(
            shop_id,
            "messenger",
            external_ref=page_id,
        )
    except accounts_db.ChannelRefTaken:
        raise ApiError(
            409,
            "That Facebook Page is already connected to another shop.",
        )


def shop_for_page(page_id):
    connection = accounts_db.find_connection_by_ref(
        "messenger",
        str(page_id),
    )

    return connection["shop_id"] if connection else None


# ---------------------------------------------------------------------
# SHARED
# ---------------------------------------------------------------------

def remove(shop_id, channel):
    if not accounts_db.delete_connection(shop_id, channel):
        raise ApiError(404, f"{channel} is not connected.")