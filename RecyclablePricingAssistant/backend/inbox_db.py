# inbox_db.py - classified customer messages. Every function is scoped to one shop,
# so a shop can never read or change another shop's messages.
import json
import sqlite3

from backend.db import connect, now_iso

EFFECTIVE_INTENT = "COALESCE(corrected_intent, intent)"


def mask_address(address):
    """'maria.santos@gmail.com' -> 'ma***@gmail.com', '+639171234567' -> '+63917***4567'."""
    address = (address or "").strip()
    if not address:
        return ""
    if "@" in address:
        name, _, domain = address.partition("@")
        return f"{name[:2]}***@{domain}"
    if len(address) > 8:
        return f"{address[:5]}***{address[-4:]}"
    return address[:2] + "***"


def _to_dict(row):
    if row is None:
        return None
    record = dict(row)
    # The full reply address stays on the server; the app only sees a masked hint.
    record["reply_hint"] = mask_address(record.pop("reply_address", None))
    record["needs_review"] = bool(record["needs_review"])
    if "followup_unread" in record:
        record["followup_unread"] = bool(record["followup_unread"])
    materials = record.pop("materials_json")
    corrected = record.pop("corrected_materials_json")
    record["materials"] = json.loads(materials) if materials else None
    record["corrected_materials"] = json.loads(corrected) if corrected else None
    return record


def get_message(shop_id, message_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ? AND shop_id = ?", (message_id, shop_id)
        ).fetchone()
    return _to_dict(row)


def find_by_external(shop_id, channel, external_id):
    if not external_id:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE shop_id = ? AND channel = ? AND external_id = ?",
            (shop_id, channel, external_id),
        ).fetchone()
    return _to_dict(row)


def get_reply_address(shop_id, message_id):
    with connect() as conn:
        row = conn.execute("SELECT reply_address FROM messages WHERE id = ? AND shop_id = ?",
                           (message_id, shop_id)).fetchone()
    return row["reply_address"] if row else None

def delete_message(shop_id, message_id):
    """Remove one inquiry and the replies that were sent for it. Returns True if it existed."""
    with connect() as conn:
        conn.execute("DELETE FROM message_replies WHERE message_id = ? AND shop_id = ?", (message_id, shop_id))
        cur = conn.execute("DELETE FROM messages WHERE id = ? AND shop_id = ?", (message_id, shop_id))
    return cur.rowcount > 0

def insert_message(shop_id, channel, sender, text, received_at, intent, intent_confidence,
                   needs_review, materials, external_id=None, subject=None, reply_address=None,
                   parent_id=None):
    """Return (record, created). created is False when it was a duplicate."""
    try:
        with connect() as conn:
            new_id = conn.execute(
                """INSERT INTO messages
                   (shop_id, channel, external_id, sender, subject, text, received_at, created_at,
                    intent, intent_confidence, needs_review, materials_json, reply_address, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop_id, channel, external_id, sender, subject, text, received_at or now_iso(),
                 now_iso(), intent, intent_confidence, int(needs_review),
                 json.dumps(materials) if materials is not None else None, reply_address, parent_id),
            ).lastrowid
    except sqlite3.IntegrityError:
        return find_by_external(shop_id, channel, external_id), False
    return get_message(shop_id, new_id), True


def list_messages(shop_id, channel=None, intent=None, needs_review=None, status=None,
                  limit=50, offset=0):
    where, params = ["shop_id = ?", "parent_id IS NULL"], [shop_id]      # follow-ups live inside their inquiry
    if channel:
        where.append("channel = ?"); params.append(channel)
    if intent:
        where.append(f"{EFFECTIVE_INTENT} = ?"); params.append(intent)
    if needs_review is not None:
        where.append("needs_review = ?"); params.append(int(needs_review))
    if status:
        where.append("status = ?"); params.append(status)
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT messages.*,
                       (SELECT c.text    FROM messages c WHERE c.parent_id = messages.id ORDER BY c.id DESC LIMIT 1) AS last_followup_text,
                       (SELECT c.subject FROM messages c WHERE c.parent_id = messages.id ORDER BY c.id DESC LIMIT 1) AS last_followup_subject
                FROM messages WHERE {' AND '.join(where)}
                ORDER BY COALESCE((SELECT MAX(c.id) FROM messages c
                                   WHERE c.parent_id = messages.id AND c.handled_note IS NULL), messages.id) DESC,
                         messages.id DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
    out = []
    for r in rows:
        record = _to_dict(r)
        record["last_followup_text"] = strip_subject(record["last_followup_text"], record.pop("last_followup_subject"))
        out.append(record)
    return out


def review_message(shop_id, message_id, intent=None, materials=None, reviewer_id=None):
    """Operator confirms (no changes) or corrects the predicted labels."""
    record = get_message(shop_id, message_id)
    if record is None:
        return None

    predicted = sorted(record["materials"]["labels"]) if record["materials"] else []
    corrected_intent = intent if intent is not None and intent != record["intent"] else None
    corrected_materials = (
        sorted(materials) if materials is not None and sorted(materials) != predicted else None
    )
    status = "corrected" if (corrected_intent or corrected_materials is not None) else "confirmed"

    with connect() as conn:
        conn.execute(
            """UPDATE messages SET status = ?, corrected_intent = ?, corrected_materials_json = ?,
               reviewed_at = ?, reviewed_by = ? WHERE id = ? AND shop_id = ?""",
            (status, corrected_intent,
             json.dumps(corrected_materials) if corrected_materials is not None else None,
             now_iso(), reviewer_id, message_id, shop_id),
        )
    return get_message(shop_id, message_id)


def mark_handled(shop_id, message_id, note=None):
    """The app dealt with this message itself (e.g. a YES to the price-update invitation), so it
    does not need to wait in the 'needs review' list. `note` is the short label shown on it."""
    with connect() as conn:
        conn.execute("UPDATE messages SET needs_review = 0, handled_note = ? WHERE id = ? AND shop_id = ?",
                     (note, message_id, shop_id))


def stats(shop_id):
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM messages WHERE shop_id = ? AND parent_id IS NULL", (shop_id,)).fetchone()[0]
        by_channel = conn.execute(
            "SELECT channel, COUNT(*) c FROM messages WHERE shop_id = ? AND parent_id IS NULL GROUP BY channel", (shop_id,)
        ).fetchall()
        by_intent = conn.execute(
            f"SELECT {EFFECTIVE_INTENT} i, COUNT(*) c FROM messages WHERE shop_id = ? AND parent_id IS NULL GROUP BY i", (shop_id,)
        ).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE shop_id = ? AND parent_id IS NULL AND needs_review = 1 AND status = 'new'",
            (shop_id,),
        ).fetchone()[0]
    return {
        "total": total,
        "pending_review": pending,
        "by_channel": {r["channel"]: r["c"] for r in by_channel},
        "by_intent": {r["i"]: r["c"] for r in by_intent},
    }


#  conversations: a customer's answer belongs to the inquiry it answers
def strip_subject(text, subject):
    """Emails are stored as "subject\nbody"; the conversation only needs the body."""
    text = (text or "").strip()
    subject = (subject or "").strip()
    if subject and text.lower().startswith(subject.lower()):
        text = text[len(subject):].strip()
    return text


def root_id(shop_id, message_id):
    """The inquiry a message belongs to: itself, or the inquiry it is a follow-up of."""
    with connect() as conn:
        row = conn.execute("SELECT id, parent_id FROM messages WHERE id = ? AND shop_id = ?",
                           (message_id, shop_id)).fetchone()
    return None if row is None else (row["parent_id"] or row["id"])


def child_ids(shop_id, message_id):
    with connect() as conn:
        rows = conn.execute("SELECT id FROM messages WHERE shop_id = ? AND parent_id = ? ORDER BY id",
                            (shop_id, message_id)).fetchall()
    return [r["id"] for r in rows]


def list_followups(shop_id, root):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE shop_id = ? AND parent_id = ? ORDER BY id",
                            (shop_id, root)).fetchall()
    out = []
    for row in rows:
        r = _to_dict(row)
        out.append({"id": r["id"], "sender": r["sender"], "channel": r["channel"], "created_at": r["created_at"],
                    "received_at": r["received_at"], "text": strip_subject(r["text"], r["subject"]),
                    "intent": r["corrected_intent"] or r["intent"], "handled_note": r["handled_note"]})
    return out


def find_thread_by_references(shop_id, channel, reference_ids):
    """Email: the customer's reply names the message it answers (In-Reply-To / References)."""
    ids = [i for i in dict.fromkeys(reference_ids or []) if i]
    if not ids:
        return None
    marks = ",".join("?" * len(ids))
    with connect() as conn:
        row = conn.execute(f"SELECT id, parent_id FROM messages WHERE shop_id = ? AND channel = ? "
                           f"AND external_id IN ({marks}) ORDER BY id LIMIT 1", (shop_id, channel, *ids)).fetchone()
    return None if row is None else (row["parent_id"] or row["id"])


def find_thread_by_recent_reply(shop_id, channel, reply_address, window_hours):
    """SMS / Messenger have no thread information. A message counts as an answer when the shop has
    already replied to this same customer's latest inquiry within `window_hours`."""
    if not reply_address:
        return None
    with connect() as conn:
        root = conn.execute("""SELECT id FROM messages WHERE shop_id = ? AND channel = ? AND reply_address = ?
                               AND parent_id IS NULL ORDER BY id DESC LIMIT 1""",
                            (shop_id, channel, reply_address)).fetchone()
        if root is None:
            return None
        family = [root["id"], *child_ids(shop_id, root["id"])]
        marks = ",".join("?" * len(family))
        last = conn.execute(f"SELECT MAX(sent_at) AS t FROM message_replies WHERE shop_id = ? AND status = 'sent' "
                            f"AND message_id IN ({marks})", (shop_id, *family)).fetchone()["t"]
    if not last:
        return None
    from datetime import datetime, timedelta, timezone
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    return root["id"] if age <= timedelta(hours=window_hours) else None


def note_followup(shop_id, root, unread=True):
    """A customer answered: flag the inquiry and move it to the top of the inbox."""
    with connect() as conn:
        conn.execute("UPDATE messages SET last_followup_at = ?, followup_unread = ? WHERE id = ? AND shop_id = ?",
                     (now_iso(), 1 if unread else 0, root, shop_id))


def clear_followup_unread(shop_id, root):
    with connect() as conn:
        conn.execute("UPDATE messages SET followup_unread = 0 WHERE id = ? AND shop_id = ?", (root, shop_id))


def list_thread_replies(shop_id, ids):
    """Every reply the shop sent in this conversation (on the inquiry or on any follow-up)."""
    marks = ",".join("?" * len(ids))
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT r.*, u.full_name AS sent_by_name FROM message_replies r
                LEFT JOIN users u ON u.id = r.sent_by
                WHERE r.shop_id = ? AND r.message_id IN ({marks}) ORDER BY r.id""",
            (shop_id, *ids)).fetchall()
    return [dict(r) for r in rows]


#  replies sent from the app
def add_reply(shop_id, message_id, channel, to_hint, subject, body, status, error, sent_by):
    with connect() as conn:
        reply_id = conn.execute(
            """INSERT INTO message_replies
               (shop_id, message_id, channel, to_hint, subject, body, status, error, sent_by, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (shop_id, message_id, channel, to_hint, subject, body, status, error, sent_by, now_iso()),
        ).lastrowid
        if status == "sent":
            conn.execute("UPDATE messages SET replied_at = ? WHERE id = ? AND shop_id = ?",
                         (now_iso(), message_id, shop_id))
        row = conn.execute("SELECT * FROM message_replies WHERE id = ?", (reply_id,)).fetchone()
    return dict(row)


def list_replies(shop_id, message_id):
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.*, u.full_name AS sent_by_name FROM message_replies r
               LEFT JOIN users u ON u.id = r.sent_by
               WHERE r.shop_id = ? AND r.message_id = ? ORDER BY r.id""",
            (shop_id, message_id)).fetchall()
    return [dict(r) for r in rows]