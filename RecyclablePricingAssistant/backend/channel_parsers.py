# channel_parsers.py - normalize incoming SMS, Messenger, and email messages.
import hashlib
import hmac
import re
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

MAX_TEXT_CHARS = 4000


# ---------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------

_SENDER_KEYS = (
    "sender",
    "from",
    "phone",
    "number",
    "address",
    "msisdn",
)

_TEXT_KEYS = (
    "text",
    "message",
    "body",
    "content",
    "sms",
    "msg",
)

_ID_KEYS = (
    "id",
    "message_id",
    "messageid",
    "sid",
    "uuid",
)


def normalize_sms_payload(payload: dict) -> dict:
    """Accept common field names used by SMS-forwarding apps and gateways."""
    lowered = {
        str(key).lower(): value
        for key, value in payload.items()
    }

    def pick(keys):
        for key in keys:
            value = lowered.get(key)

            if value not in (None, ""):
                return str(value).strip()

        return None

    text = pick(_TEXT_KEYS)

    if not text:
        raise ValueError(
            "No message text found. Send a JSON field named 'text' or 'message'."
        )

    return {
        "sender": pick(_SENDER_KEYS) or "unknown",
        "text": text[:MAX_TEXT_CHARS],
        "external_id": pick(_ID_KEYS),
    }


# ---------------------------------------------------------------------
# FACEBOOK MESSENGER
# ---------------------------------------------------------------------

def verify_messenger_signature(
    raw_body: bytes,
    header,
    app_secret,
) -> bool:
    """
    Verify Meta's X-Hub-Signature-256 header.

    As in the original project, signature verification is bypassed if
    FB_APP_SECRET is not configured. Configure it for production use.
    """
    if not app_secret:
        return True

    if not header or not header.startswith("sha256="):
        return False

    expected = hmac.new(
        app_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected,
        header.split("=", 1)[1],
    )


def parse_messenger_payload(payload: dict) -> list:
    """Return one record per customer text message in a Messenger webhook."""
    items = []

    if not isinstance(payload, dict) or payload.get("object") != "page":
        return items

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            text = message.get("text")

            # Ignore stickers, non-text messages, and messages sent by the Page.
            if not text or message.get("is_echo"):
                continue

            received_at = None

            if isinstance(event.get("timestamp"), (int, float)):
                received_at = datetime.fromtimestamp(
                    event["timestamp"] / 1000,
                    tz=timezone.utc,
                ).isoformat(timespec="seconds")

            items.append({
                "page_id": entry.get("id"),
                "sender": (event.get("sender") or {}).get(
                    "id",
                    "unknown",
                ),
                "text": text.strip()[:MAX_TEXT_CHARS],
                "external_id": message.get("mid"),
                "received_at": received_at,
            })

    return items


# ---------------------------------------------------------------------
# EMAIL HTML CLEANING
# ---------------------------------------------------------------------

class _HTMLToText(HTMLParser):
    _BLOCKS = {
        "p",
        "div",
        "br",
        "tr",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "table",
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    return "".join(parser.parts)


_CUT_LINE = re.compile(
    r"^(on .{5,200} wrote:?|-{2,}\s*(original|forwarded) message\s*-{2,}|_{5,}|from:\s.+)$",
    re.IGNORECASE,
)

_SIGN_OFF = re.compile(
    r"^sent from my .+",
    re.IGNORECASE,
)

_SUBJECT_PREFIX = re.compile(
    r"^(?:\s*(?:re|fwd?|fw)\s*:\s*)+",
    re.IGNORECASE,
)


def clean_email_body(text: str) -> str:
    """Remove quoted replies, signatures, and common phone sign-offs."""
    kept = []

    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()

        if stripped in ("--", "-- ") or _CUT_LINE.match(stripped):
            break

        if stripped.startswith(">") or _SIGN_OFF.match(stripped):
            continue

        kept.append(stripped)

    return re.sub(
        r"\n{3,}",
        "\n\n",
        "\n".join(kept),
    ).strip()


# ---------------------------------------------------------------------
# EMAIL PARSING
# ---------------------------------------------------------------------

def parse_email_bytes(raw: bytes) -> dict:
    """
    Parse a raw email into a message record.

    Privacy change:
    - Show the sender's display name when available.
    - Never use the sender's raw email address as the inbox display name.
    - If no display name exists, use the generic label "Email customer".
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)

    subject = _SUBJECT_PREFIX.sub(
        "",
        str(message.get("subject") or ""),
    ).strip()

    name, _address = parseaddr(
        str(message.get("from") or "")
    )
    
    _reply_name, reply_address = parseaddr(str(message.get("reply-to") or ""))
    reply_address = (reply_address or _address or "").strip().lower() or None

    sender = (
        name.strip()
        if name and name.strip()
        else "Email customer"
    )

    message_id = str(
        message.get("message-id") or ""
    ).strip() or None

    received_at = None

    try:
        received_at = (
            parsedate_to_datetime(str(message["date"]))
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
        )
    except (TypeError, ValueError, KeyError):
        pass

    body = ""
    part = message.get_body(
        preferencelist=("plain", "html")
    )

    if part is not None:
        content = part.get_content()

        if part.get_content_type() == "text/html":
            body = html_to_text(content)
        else:
            body = content

    body = clean_email_body(body)

    text = f"{subject}\n{body}".strip() if subject else body

    return {
        "sender": sender,
        "subject": subject or None,
        "text": text[:MAX_TEXT_CHARS],
        "external_id": message_id,
        "received_at": received_at,
        "reply_address": reply_address,
    }