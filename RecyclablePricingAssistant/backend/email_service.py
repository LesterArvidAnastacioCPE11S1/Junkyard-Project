# email_service.py - reads each shop's own mailbox over IMAP and files new emails in its inbox.
# Only the mailbox a shop owner connects is read, and only UNREAD messages.
import asyncio
import imaplib

from backend import accounts_db, security
from backend.channel_parsers import parse_email_bytes
from backend.errors import ApiError
from backend.inbox_service import ingest_message

IMAP_TIMEOUT = 20


def _friendly(error: Exception) -> str:
    name = type(error).__name__
    if name == "InvalidToken":
        return "The saved mailbox password can't be read (APP_SECRET changed?). Reconnect the email."
    if isinstance(error, imaplib.IMAP4.error):
        return ("The mailbox rejected the login. For Gmail, use an App Password and make sure IMAP is on.")
    if isinstance(error, OSError):
        return f"Could not reach the mail server: {error}"
    if isinstance(error, RuntimeError):
        return str(error)
    return f"{name}: {error}"


def test_imap_login(host, user, password, folder="INBOX"):
    """Try the credentials once. Raises ApiError(400) with a readable reason on failure."""
    try:
        imap = imaplib.IMAP4_SSL(host, timeout=IMAP_TIMEOUT)
        try:
            imap.login(user, password)
            status, _ = imap.select(folder, readonly=True)
            if status != "OK":
                raise ApiError(400, f"The folder '{folder}' was not found in that mailbox.")
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except ApiError:
        raise
    except (imaplib.IMAP4.error, OSError) as error:
        raise ApiError(400, _friendly(error))


def _fetch_and_ingest(shop_id, host, user, password, folder):
    imap = imaplib.IMAP4_SSL(host, timeout=IMAP_TIMEOUT)
    handled = 0
    try:
        imap.login(user, password)
        imap.select(folder)
        status, data = imap.uid("search", None, "UNSEEN")
        uids = data[0].split() if status == "OK" and data and data[0] else []

        for uid in uids:
            status, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue

            item = parse_email_bytes(parts[0][1])
            if not item["text"]:                       # empty message, nothing to classify
                imap.uid("store", uid, "+FLAGS", "\\Seen")
                continue
            external_id = item["external_id"] or f"{user}:{uid.decode()}"

            _, created = ingest_message(
                shop_id, "email", item["sender"], item["text"], external_id=external_id,
                received_at=item["received_at"], subject=item["subject"],
            )
            imap.uid("store", uid, "+FLAGS", "\\Seen")  # only after it was stored
            handled += int(created)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return handled


def poll_shop(shop_id: int) -> dict:
    """Check one shop's mailbox now. Never raises; the result says what happened."""
    connection = accounts_db.get_connection(shop_id, "email")
    if connection is None:
        return {"connected": False, "new": 0, "error": "Email is not connected."}
    try:
        config = connection["config"]
        password = security.decrypt_secret(connection["secret_enc"])
        new = _fetch_and_ingest(shop_id, config["imap_host"], config["imap_user"],
                                password, config.get("folder", "INBOX"))
        accounts_db.set_check_result(shop_id, "email", None)
        return {"connected": True, "new": new, "error": None}
    except Exception as error:   # keep the background loop alive whatever goes wrong
        message = _friendly(error)
        accounts_db.set_check_result(shop_id, "email", message)
        print(f"[email] shop {shop_id}: {message}")
        return {"connected": True, "new": 0, "error": message}


def poll_all():
    for connection in accounts_db.list_connections_by_channel("email"):
        poll_shop(connection["shop_id"])


async def poll_loop(interval_seconds: int):
    """Background task started by the API: checks every shop's mailbox on a timer."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(poll_all)
        except Exception as error:
            print(f"[email] background check failed: {error}")
