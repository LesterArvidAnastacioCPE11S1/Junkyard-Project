# subscriptions.py - who agreed to receive price forecasts, and how they agreed.

import re
from datetime import datetime, timedelta, timezone

from backend.db import connect, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_subscribers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id             INTEGER NOT NULL REFERENCES shops(id),
    channel             TEXT    NOT NULL,
    address             TEXT    NOT NULL,           -- email / phone / Messenger id, kept on the server only
    name                TEXT,
    status              TEXT    NOT NULL CHECK (status IN ('invited', 'subscribed', 'declined', 'unsubscribed')),
    invited_at          TEXT,
    invite_message_id   INTEGER,                    -- the inquiry the invitation was sent in reply to
    responded_at        TEXT,
    consent_message_id  INTEGER,                    -- the customer's own YES (proof of consent)
    consent_text        TEXT,
    last_sent_at        TEXT,
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (shop_id, channel, address)
);
CREATE INDEX IF NOT EXISTS ix_price_subs_shop ON price_subscribers(shop_id, status);

CREATE TABLE IF NOT EXISTS price_update_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id    INTEGER NOT NULL REFERENCES shops(id),
    sent_by    INTEGER REFERENCES users(id),
    sent_at    TEXT    NOT NULL,
    recipients INTEGER NOT NULL,
    delivered  INTEGER NOT NULL,
    failed     INTEGER NOT NULL,
    body       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_price_runs_shop ON price_update_runs(shop_id, id);
"""

INVITE_VALID_DAYS = 7          # a YES is only taken as consent for this long after the invitation

# The invitation added to a price reply. The words "Reply YES" are what the server looks for to
# know that an invitation really went out, so an operator who edits the line away sends no invite.
OFFER_LINE = ("Would you like to receive our price updates and next-day price forecasts? "
              "Reply YES to get them. You can reply STOP anytime to unsubscribe.")
_OFFER_PATTERN = re.compile(r"reply\s+yes", re.I)


def init_subscriptions_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def contains_offer(body):
    return bool(_OFFER_PATTERN.search(body or ""))


def normalize_address(address):
    return (address or "").strip().lower().replace(" ", "")


# reading a customer's answer
# Only a short message that is essentially just an answer counts, so "Yes po, magkano ang karton?"
# (a real question) is never taken as consent.
_YES = {"yes", "y", "yep", "yeah", "yup", "oo", "opo", "sige", "game", "ok", "okay", "sure", "subscribe",
        "gusto", "go", "tuloy", "pwede", "payag"}
_NO = {"no", "nope", "hindi", "ayoko", "ayaw", "huwag", "wag", "later", "mamaya", "nah"}
_STOP = {"stop", "unsubscribe", "cancel", "tigil", "tigilan", "unsub", "quit", "end"}
_FILLER = {"po", "ho", "please", "pls", "plz", "naman", "ako", "ko", "sir", "maam", "mam", "boss", "ma'am",
           "thanks", "thank", "you", "salamat", "lang", "na", "ay", "update", "updates", "ng", "sending",
           "kayo", "yung", "ang", "mga", "sa", "price", "prices", "text", "me", "i", "want", "would", "like",
           "to", "get", "them", "it", "pa", "din", "rin", "talaga", "sana", "gustong", "makatanggap",
           "mag", "again", "now", "this", "that", "of"}
MAX_ANSWER_WORDS = 6


def classify_reply(text):
    """'yes', 'no', 'stop' or None (not an answer to the invitation)."""
    tokens = re.findall(r"[a-z']+", (text or "").lower())
    if not tokens or len(tokens) > MAX_ANSWER_WORDS:
        return None
    words = set(tokens)
    if words & _STOP:
        return "stop" if words <= (_STOP | _FILLER | _YES | _NO) else None
    if words & _NO:
        return "no" if words <= (_NO | _FILLER) else None
    if words & _YES:
        return "yes" if words <= (_YES | _FILLER) else None
    return None


# reading and writing subscribers
def _row(row):
    return dict(row) if row else None


def get(shop_id, channel, address):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM price_subscribers WHERE shop_id = ? AND channel = ? AND address = ?",
            (shop_id, channel, normalize_address(address))).fetchone())


def _invite_expired(sub):
    if not sub["invited_at"]:
        return True
    invited = datetime.fromisoformat(sub["invited_at"])
    return datetime.now(timezone.utc) - invited > timedelta(days=INVITE_VALID_DAYS)


def record_invite(shop_id, channel, address, name, message_id):
    """The shop has just sent the invitation. Never touches someone who is already subscribed."""
    address = normalize_address(address)
    if not address:
        return None
    now = now_iso()
    with connect() as conn:
        row = conn.execute("SELECT * FROM price_subscribers WHERE shop_id = ? AND channel = ? AND address = ?",
                           (shop_id, channel, address)).fetchone()
        if row is None:
            conn.execute("""INSERT INTO price_subscribers
                            (shop_id, channel, address, name, status, invited_at, invite_message_id, created_at)
                            VALUES (?, ?, ?, ?, 'invited', ?, ?, ?)""",
                         (shop_id, channel, address, name, now, message_id, now))
        elif row["status"] != "subscribed":
            conn.execute("""UPDATE price_subscribers SET status = 'invited', invited_at = ?, invite_message_id = ?,
                            responded_at = NULL WHERE id = ?""", (now, message_id, row["id"]))
    return get(shop_id, channel, address)


def apply_answer(shop_id, channel, address, text, message_id):
    """A customer message arrived. Returns {'action': ..., 'subscriber': ...} when it was an answer
    to our invitation (or a STOP), otherwise None and nothing changes."""
    sub = get(shop_id, channel, address)
    if sub is None:
        return None
    answer = classify_reply(text)
    if answer is None:
        return None
    now = now_iso()
    new_status = action = None

    if sub["status"] == "invited" and not _invite_expired(sub):
        if answer == "yes":
            new_status, action = "subscribed", "subscribed"
        elif answer == "no":
            new_status, action = "declined", "declined"
        else:
            new_status, action = "unsubscribed", "unsubscribed"
    elif sub["status"] == "subscribed" and answer == "stop":
        new_status, action = "unsubscribed", "unsubscribed"
    if new_status is None:
        return None

    with connect() as conn:
        if new_status == "subscribed":
            conn.execute("""UPDATE price_subscribers SET status = 'subscribed', responded_at = ?,
                            consent_message_id = ?, consent_text = ?, last_error = NULL WHERE id = ?""",
                         (now, message_id, (text or "")[:200], sub["id"]))
        else:
            conn.execute("UPDATE price_subscribers SET status = ?, responded_at = ? WHERE id = ?",
                         (new_status, now, sub["id"]))
    return {"action": action, "subscriber": get(shop_id, channel, address)}


def list_subscribers(shop_id, status=None):
    where, params = ["shop_id = ?"], [shop_id]
    if status:
        where.append("status = ?"); params.append(status)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM price_subscribers WHERE {' AND '.join(where)} ORDER BY id DESC",
                            params).fetchall()
    return [dict(r) for r in rows]


def counts(shop_id):
    with connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) c FROM price_subscribers WHERE shop_id = ? GROUP BY status",
                            (shop_id,)).fetchall()
    out = {"invited": 0, "subscribed": 0, "declined": 0, "unsubscribed": 0}
    out.update({r["status"]: r["c"] for r in rows})
    return out


def set_status(shop_id, subscriber_id, status):
    """Operator removes someone (or marks them unsubscribed). Subscribing is never done this way."""
    if status not in ("unsubscribed",):
        raise ValueError("Only unsubscribing can be done by staff.")
    with connect() as conn:
        cur = conn.execute("UPDATE price_subscribers SET status = 'unsubscribed', responded_at = ? "
                           "WHERE id = ? AND shop_id = ?", (now_iso(), subscriber_id, shop_id))
    return cur.rowcount > 0


def mark_sent(subscriber_id, error=None):
    with connect() as conn:
        if error:
            conn.execute("UPDATE price_subscribers SET last_error = ? WHERE id = ?", (error[:300], subscriber_id))
        else:
            conn.execute("UPDATE price_subscribers SET last_sent_at = ?, last_error = NULL WHERE id = ?",
                         (now_iso(), subscriber_id))


def message_status(shop_id, message):
    """What the inquiry screen needs: the customer's status and whether to add the offer to the reply."""
    sub = get(shop_id, message["channel"], _address_of(shop_id, message))
    status = sub["status"] if sub else "none"
    can_offer = status == "none" or (status == "invited" and _invite_expired(sub))
    return {"status": status, "can_offer": bool(can_offer), "offer_line": OFFER_LINE}


def _address_of(shop_id, message):
    from backend import inbox_db
    return inbox_db.get_reply_address(shop_id, message["id"])


def log_run(shop_id, user_id, recipients, delivered, failed, body):
    with connect() as conn:
        return conn.execute("""INSERT INTO price_update_runs (shop_id, sent_by, sent_at, recipients, delivered, failed, body)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (shop_id, user_id, now_iso(), recipients, delivered, failed, body)).lastrowid


def recent_runs(shop_id, limit=5):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM price_update_runs WHERE shop_id = ? ORDER BY id DESC LIMIT ?",
                            (shop_id, limit)).fetchall()
    return [dict(r) for r in rows]