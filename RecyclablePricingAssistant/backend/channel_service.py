# channel_service.py - each shop's own email / SMS / Messenger connections.
import hmac

from backend import accounts_db, email_service, security
from backend.errors import ApiError


def get_status(shop_id: int) -> dict:
    """What is connected. Never returns passwords or full keys."""
    status = {
        "email": {"connected": False},
        "sms": {"enabled": False, "webhook_path": f"/webhooks/sms/{shop_id}"},
        "messenger": {"connected": False},
    }
    for connection in accounts_db.list_connections(shop_id):
        if connection["channel"] == "email":
            config = connection["config"]
            status["email"] = {
                "connected": True,
                "imap_host": config.get("imap_host"),
                "imap_user": config.get("imap_user"),
                "folder": config.get("folder", "INBOX"),
                "last_checked_at": connection["last_checked_at"],
                "last_error": connection["last_error"],
            }
        elif connection["channel"] == "sms":
            status["sms"].update({"enabled": True, "key_hint": connection["secret_hint"] + "…"})
        elif connection["channel"] == "messenger":
            status["messenger"] = {"connected": True, "page_id": connection["external_ref"]}
    return status


#  email
def set_email(shop_id, imap_host, imap_user, imap_password, folder="INBOX"):
    host, user, folder = imap_host.strip(), imap_user.strip(), (folder or "INBOX").strip()
    email_service.test_imap_login(host, user, imap_password, folder)   # fail early, with a reason
    try:
        encrypted = security.encrypt_secret(imap_password)
    except RuntimeError as error:
        raise ApiError(503, str(error))
    try:
        accounts_db.upsert_connection(
            shop_id, "email", external_ref=user.lower(),
            config={"imap_host": host, "imap_user": user, "folder": folder},
            secret_enc=encrypted,
        )
    except accounts_db.ChannelRefTaken:
        raise ApiError(409, "That mailbox is already connected to another shop.")


#  SMS
def regenerate_sms_key(shop_id) -> str:
    """Create (or replace) the key the phone's SMS-forwarder app uses. Shown only once."""
    key = security.new_api_key()
    accounts_db.upsert_connection(
        shop_id, "sms", secret_hash=security.token_hash(key), secret_hint=key[:8],
    )
    return key


def verify_sms_key(shop_id: int, key) -> bool:
    connection = accounts_db.get_connection(shop_id, "sms")
    if connection is None or not key:
        security.burn_password_time(key or "")      # keep timing similar
        return False
    return hmac.compare_digest(connection["secret_hash"] or "", security.token_hash(key))


#  Messenger
def set_messenger(shop_id, page_id):
    try:
        accounts_db.upsert_connection(shop_id, "messenger", external_ref=page_id.strip())
    except accounts_db.ChannelRefTaken:
        raise ApiError(409, "That Facebook Page is already connected to another shop.")


def shop_for_page(page_id):
    connection = accounts_db.find_connection_by_ref("messenger", str(page_id))
    return connection["shop_id"] if connection else None


#  shared
def remove(shop_id, channel):
    if not accounts_db.delete_connection(shop_id, channel):
        raise ApiError(404, f"{channel} is not connected.")
