# inbox_db.py - SQLite storage for classified customer messages (standard library only).
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    channel                  TEXT    NOT NULL,
    external_id              TEXT,
    sender                   TEXT,
    subject                  TEXT,
    text                     TEXT    NOT NULL,
    received_at              TEXT    NOT NULL,
    created_at               TEXT    NOT NULL,
    intent                   TEXT    NOT NULL,
    intent_confidence        REAL    NOT NULL,
    needs_review             INTEGER NOT NULL,
    materials_json           TEXT,
    status                   TEXT    NOT NULL DEFAULT 'new',
    corrected_intent         TEXT,
    corrected_materials_json TEXT,
    reviewed_at              TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_channel_external
    ON messages(channel, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_messages_id ON messages(id);
"""

EFFECTIVE_INTENT = "COALESCE(corrected_intent, intent)"


def db_path() -> Path:
    return Path(os.environ.get("INBOX_DB") or Path(__file__).resolve().parent / "inbox.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


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


def get_message(message_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return _to_dict(row)


def find_by_external(channel, external_id):
    if not external_id:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE channel = ? AND external_id = ?",
            (channel, external_id),
        ).fetchone()
    return _to_dict(row)


def insert_message(channel, sender, text, received_at, intent, intent_confidence,
                   needs_review, materials, external_id=None, subject=None):
    """Return (record, created). created is False when it was a duplicate."""
    try:
        with connect() as conn:
            cur = conn.execute(
                """INSERT INTO messages
                   (channel, external_id, sender, subject, text, received_at, created_at,
                    intent, intent_confidence, needs_review, materials_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (channel, external_id, sender, subject, text, received_at or now_iso(),
                 now_iso(), intent, intent_confidence, int(needs_review),
                 json.dumps(materials) if materials is not None else None),
            )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return find_by_external(channel, external_id), False
    return get_message(new_id), True


def list_messages(channel=None, intent=None, needs_review=None, status=None,
                  limit=50, offset=0):
    where, params = [], []
    if channel:
        where.append("channel = ?"); params.append(channel)
    if intent:
        where.append(f"{EFFECTIVE_INTENT} = ?"); params.append(intent)
    if needs_review is not None:
        where.append("needs_review = ?"); params.append(int(needs_review))
    if status:
        where.append("status = ?"); params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM messages {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_to_dict(r) for r in rows]


def review_message(message_id, intent=None, materials=None):
    """Operator confirms (no changes) or corrects the predicted labels."""
    record = get_message(message_id)
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
            """UPDATE messages SET status = ?, corrected_intent = ?,
               corrected_materials_json = ?, reviewed_at = ? WHERE id = ?""",
            (status, corrected_intent,
             json.dumps(corrected_materials) if corrected_materials is not None else None,
             now_iso(), message_id),
        )
    return get_message(message_id)


def stats():
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        by_channel = conn.execute(
            "SELECT channel, COUNT(*) c FROM messages GROUP BY channel").fetchall()
        by_intent = conn.execute(
            f"SELECT {EFFECTIVE_INTENT} i, COUNT(*) c FROM messages GROUP BY i").fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE needs_review = 1 AND status = 'new'"
        ).fetchone()[0]
    return {
        "total": total,
        "pending_review": pending,
        "by_channel": {r["channel"]: r["c"] for r in by_channel},
        "by_intent": {r["i"]: r["c"] for r in by_intent},
    }