# inbox_db.py - classified customer messages. Every function is scoped to one shop,
# so a shop can never read or change another shop's messages.
import json
import sqlite3

from backend.db import connect, now_iso

EFFECTIVE_INTENT = "COALESCE(corrected_intent, intent)"


def _to_dict(row):
    if row is None:
        return None
    record = dict(row)
    record["needs_review"] = bool(record["needs_review"])
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


def insert_message(shop_id, channel, sender, text, received_at, intent, intent_confidence,
                   needs_review, materials, external_id=None, subject=None):
    """Return (record, created). created is False when it was a duplicate."""
    try:
        with connect() as conn:
            new_id = conn.execute(
                """INSERT INTO messages
                   (shop_id, channel, external_id, sender, subject, text, received_at, created_at,
                    intent, intent_confidence, needs_review, materials_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop_id, channel, external_id, sender, subject, text, received_at or now_iso(),
                 now_iso(), intent, intent_confidence, int(needs_review),
                 json.dumps(materials) if materials is not None else None),
            ).lastrowid
    except sqlite3.IntegrityError:
        return find_by_external(shop_id, channel, external_id), False
    return get_message(shop_id, new_id), True


def list_messages(shop_id, channel=None, intent=None, needs_review=None, status=None,
                  limit=50, offset=0):
    where, params = ["shop_id = ?"], [shop_id]
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
            f"SELECT * FROM messages WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_to_dict(r) for r in rows]


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


def stats(shop_id):
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM messages WHERE shop_id = ?", (shop_id,)).fetchone()[0]
        by_channel = conn.execute(
            "SELECT channel, COUNT(*) c FROM messages WHERE shop_id = ? GROUP BY channel", (shop_id,)
        ).fetchall()
        by_intent = conn.execute(
            f"SELECT {EFFECTIVE_INTENT} i, COUNT(*) c FROM messages WHERE shop_id = ? GROUP BY i", (shop_id,)
        ).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE shop_id = ? AND needs_review = 1 AND status = 'new'",
            (shop_id,),
        ).fetchone()[0]
    return {
        "total": total,
        "pending_review": pending,
        "by_channel": {r["channel"]: r["c"] for r in by_channel},
        "by_intent": {r["i"]: r["c"] for r in by_intent},
    }
