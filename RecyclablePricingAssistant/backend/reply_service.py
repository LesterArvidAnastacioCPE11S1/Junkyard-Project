# reply_service.py - sends a reply to a customer from inside the app, over the same channel the
# customer used: email (SMTP with the shop's own mailbox), SMS (the shop's Twilio number) or
# Facebook Messenger (Page access token).

import base64
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from backend import accounts_db, inbox_db, security
from backend.errors import ApiError

TIMEOUT = 20
MAX_REPLY_CHARS = 1500


# what can this message be answered with?
def _smtp_host(config):
    if config.get("smtp_host"):
        return config["smtp_host"]
    host = (config.get("imap_host") or "").lower()
    known = {"imap.gmail.com": "smtp.gmail.com", "imap.mail.yahoo.com": "smtp.mail.yahoo.com",
             "outlook.office365.com": "smtp.office365.com", "imap-mail.outlook.com": "smtp-mail.outlook.com",
             "imap.zoho.com": "smtp.zoho.com"}
    if host in known:
        return known[host]
    return "smtp." + host.split(".", 1)[1] if host.startswith("imap.") else host


def _messenger_token(shop_id):
    connection = accounts_db.get_connection(shop_id, "messenger")
    if connection and connection.get("secret_enc"):
        try:
            return security.decrypt_secret(connection["secret_enc"])
        except Exception:                                   # noqa: BLE001
            return None
    return os.environ.get("FB_PAGE_ACCESS_TOKEN") or None


def reply_options(shop_id, message):
    """{can_reply, via, to_hint, reason} for the Reply box. `message` comes from inbox_db."""
    channel = message["channel"]
    hint = message.get("reply_hint") or ""
    address = inbox_db.get_reply_address(shop_id, message["id"])

    def no(reason):
        return {"can_reply": False, "via": channel, "to_hint": hint, "reason": reason}

    if channel == "email":
        if not address:
            return no("This email has no reply address on file.")
        if accounts_db.get_connection(shop_id, "email") is None:
            return no("Connect the shop mailbox in More to send email replies.")
        return {"can_reply": True, "via": "email", "to_hint": hint, "reason": None}
    if channel == "sms":
        if not address:
            return no("This text has no phone number on file.")
        if accounts_db.get_connection(shop_id, "sms_twilio") is None:
            return no("Replies to texts need Twilio. Connect it in More, or copy the reply and send it from your phone.")
        return {"can_reply": True, "via": "sms", "to_hint": hint, "reason": None}
    if channel == "messenger":
        if not address:
            return no("This Messenger chat has no recipient on file.")
        if not _messenger_token(shop_id):
            return no("Add the Facebook Page access token in More to reply on Messenger.")
        return {"can_reply": True, "via": "messenger", "to_hint": hint, "reason": None}
    return no("This message was typed in by hand, so there is nobody to send a reply to.")


# the three senders
def _send_email(shop_id, message, address, subject, body):
    connection = accounts_db.get_connection(shop_id, "email")
    config = connection["config"]
    user = config["imap_user"]
    password = security.decrypt_secret(connection["secret_enc"])
    shop = accounts_db.get_shop(shop_id) or {}

    mail = EmailMessage()
    mail["From"] = f"{shop.get('name') or 'ScrapDesk'} <{user}>"
    mail["To"] = address
    base = (subject or message.get("subject") or "Your inquiry").strip()
    mail["Subject"] = base if base.lower().startswith("re:") else f"Re: {base}"
    mail["Date"] = formatdate(localtime=True)
    mail["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    original = message.get("external_id")
    if original and original.startswith("<"):               # keeps the reply in the customer's thread
        mail["In-Reply-To"] = original
        mail["References"] = original
    mail.set_content(body)

    _deliver(config, user, password, mail)


def _deliver(config, user, password, mail, timeout=TIMEOUT):
    """Log in to the shop mailbox's SMTP server and send `mail`. Raises RuntimeError with a plain-language reason."""
    host = _smtp_host(config)
    context = ssl.create_default_context()
    try:
        try:
            with smtplib.SMTP_SSL(host, 465, timeout=timeout, context=context) as smtp:
                smtp.login(user, password)
                smtp.send_message(mail)
        except (ConnectionError, TimeoutError, ssl.SSLError, smtplib.SMTPConnectError):
            with smtplib.SMTP(host, 587, timeout=timeout) as smtp:      # many providers use STARTTLS here
                smtp.starttls(context=context)
                smtp.login(user, password)
                smtp.send_message(mail)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("The mail server rejected the saved login. Reconnect the email in More "
                           "(Gmail needs an App Password).")
    except (smtplib.SMTPException, OSError) as error:
        raise RuntimeError(f"Could not send the email through {host}: {error}")


def send_plain_email(shop_id, to_address, subject, body, timeout=TIMEOUT):
    """Send a one-off email from the shop's own mailbox (used for driver notices).
    Raises RuntimeError with a plain-language reason when it can't be sent."""
    connection = accounts_db.get_connection(shop_id, "email")
    if connection is None:
        raise RuntimeError("Connect the shop mailbox in More to email drivers.")
    config = connection["config"]
    user = config["imap_user"]
    password = security.decrypt_secret(connection["secret_enc"])
    shop = accounts_db.get_shop(shop_id) or {}
    mail = EmailMessage()
    mail["From"] = f"{shop.get('name') or 'ScrapDesk'} <{user}>"
    mail["To"] = to_address
    mail["Subject"] = subject
    mail["Date"] = formatdate(localtime=True)
    mail["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    mail.set_content(body)
    _deliver(config, user, password, mail, timeout)


def _post(url, data, headers):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f"Could not reach the service: {error}")


def _send_sms(shop_id, address, body):
    connection = accounts_db.get_connection(shop_id, "sms_twilio")
    sid = connection["config"].get("account_sid", "")
    token = security.decrypt_secret(connection["secret_enc"])
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    status, text = _post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        urllib.parse.urlencode({"To": address, "From": connection["external_ref"], "Body": body}).encode(),
        {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    if status >= 300:
        try:
            detail = json.loads(text).get("message", text)
        except ValueError:
            detail = text
        raise RuntimeError(f"Twilio could not send the text: {detail}"[:300])


def _send_messenger(shop_id, address, body):
    token = _messenger_token(shop_id)
    payload = json.dumps({"recipient": {"id": address}, "messaging_type": "RESPONSE",
                          "message": {"text": body}}).encode()
    status, text = _post("https://graph.facebook.com/v19.0/me/messages?" +
                         urllib.parse.urlencode({"access_token": token}),
                         payload, {"Content-Type": "application/json"})
    if status >= 300:
        try:
            detail = json.loads(text).get("error", {}).get("message", text)
        except ValueError:
            detail = text
        raise RuntimeError(f"Facebook could not deliver the message: {detail} "
                           "(Messenger only allows replies within 24 hours of the customer's message.)"[:400])


# the one entry point
def send_reply(shop_id, user, message_id, text, subject=None):
    """Send `text` to the customer who wrote message `message_id`. Returns the saved reply record."""
    message = inbox_db.get_message(shop_id, message_id)
    if message is None:
        raise ApiError(404, "Message not found.")
    body = (text or "").strip()
    if not body:
        raise ApiError(422, "Write a reply first.")
    if len(body) > MAX_REPLY_CHARS:
        raise ApiError(422, f"Replies are limited to {MAX_REPLY_CHARS} characters.")

    options = reply_options(shop_id, message)
    if not options["can_reply"]:
        raise ApiError(409, options["reason"])
    address = inbox_db.get_reply_address(shop_id, message_id)
    channel = options["via"]

    try:
        if channel == "email":
            _send_email(shop_id, message, address, subject, body)
        elif channel == "sms":
            _send_sms(shop_id, address, body)
        else:
            _send_messenger(shop_id, address, body)
    except RuntimeError as error:
        inbox_db.add_reply(shop_id, message_id, channel, options["to_hint"], subject, body, "failed",
                           str(error), user["id"])
        raise ApiError(502, str(error))
    except Exception as error:                              # noqa: BLE001 (e.g. an unreadable saved password)
        name = type(error).__name__
        reason = ("The saved login can't be read (APP_SECRET changed?). Reconnect the channel in More."
                  if name == "InvalidToken" else f"Could not send the reply ({name}).")
        inbox_db.add_reply(shop_id, message_id, channel, options["to_hint"], subject, body, "failed",
                           reason, user["id"])
        raise ApiError(502, reason)

    return inbox_db.add_reply(shop_id, message_id, channel, options["to_hint"], subject, body, "sent",
                              None, user["id"])