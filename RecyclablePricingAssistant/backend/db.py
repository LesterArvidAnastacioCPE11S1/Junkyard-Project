# db.py - the SQLite connection and the whole database schema (accounts + inbox).
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id       INTEGER NOT NULL REFERENCES shops(id),
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('owner', 'dispatcher', 'driver')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_shop ON users(shop_id);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    device_name  TEXT,
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    email   TEXT NOT NULL,
    success INTEGER NOT NULL,
    at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attempts ON login_attempts(email, at);

CREATE TABLE IF NOT EXISTS channel_connections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id         INTEGER NOT NULL REFERENCES shops(id),
    channel         TEXT NOT NULL CHECK (channel IN ('email', 'sms', 'sms_twilio', 'messenger')),
    external_ref    TEXT,     -- mailbox address or Messenger Page ID (one shop per value)
    config_json     TEXT,     -- non-secret settings
    secret_enc      TEXT,     -- encrypted mailbox password
    secret_hash     TEXT,     -- hash of the SMS webhook key
    secret_hint     TEXT,     -- first characters of the SMS key, safe to show
    last_checked_at TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (shop_id, channel)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_channel_ref
    ON channel_connections(channel, external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS messages (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id                  INTEGER NOT NULL REFERENCES shops(id),
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
    reviewed_at              TEXT,
    reviewed_by              INTEGER REFERENCES users(id),
    reply_address            TEXT,     -- where a reply goes (email address / phone / Messenger id); never shown in full
    replied_at               TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_msg_external
    ON messages(shop_id, channel, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_msg_shop ON messages(shop_id, id);

CREATE TABLE IF NOT EXISTS message_replies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id    INTEGER NOT NULL REFERENCES shops(id),
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    channel    TEXT    NOT NULL,
    to_hint    TEXT,                   -- masked recipient, e.g. ma***@gmail.com
    subject    TEXT,
    body       TEXT    NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('sent', 'failed')),
    error      TEXT,
    sent_by    INTEGER REFERENCES users(id),
    sent_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reply_msg ON message_replies(shop_id, message_id);
"""


def db_path() -> Path:
    return Path(os.environ.get("INBOX_DB") or Path(__file__).resolve().parent / "inbox.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _move_old_inbox_aside():
    """The first version of the inbox had no shops. Keep that file as a backup and start fresh."""
    path = db_path()
    if not path.exists():
        return
    conn = sqlite3.connect(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(messages)")]
    finally:
        conn.close()
    if columns and "shop_id" not in columns:
        backup = path.with_name(f"{path.stem}_before_accounts{path.suffix}")
        if backup.exists():
            backup = path.with_name(f"{path.stem}_before_accounts_{int(time.time())}{path.suffix}")
        try:
            os.replace(path, backup)
        except PermissionError:
            raise RuntimeError(f"Close any program that has {path.name} open "
                               "(for example a SQLite viewer), then start the server again.")
        print(f"[db] Old inbox saved as {backup.name}; created a new database with accounts.")


def _add_column_if_missing(conn, table, column, definition):
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if existing and column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _allow_twilio_channel(conn):
    """Older databases only allowed email / sms / messenger, so saving Twilio settings failed.
    SQLite cannot change a CHECK rule in place, so rebuild the table once and keep every row."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'channel_connections'").fetchone()
    if row is None or "sms_twilio" in (row[0] or ""):
        return
    conn.execute("ALTER TABLE channel_connections RENAME TO channel_connections_old")
    conn.execute("DROP INDEX IF EXISTS ux_channel_ref")
    conn.executescript(SCHEMA)          # creates the new table + indexes (other tables already exist)
    conn.execute("""INSERT INTO channel_connections
                    (id, shop_id, channel, external_ref, config_json, secret_enc, secret_hash,
                     secret_hint, last_checked_at, last_error, created_at)
                    SELECT id, shop_id, channel, external_ref, config_json, secret_enc, secret_hash,
                           secret_hint, last_checked_at, last_error, created_at
                    FROM channel_connections_old""")
    conn.execute("DROP TABLE channel_connections_old")

def init_db():
    _move_old_inbox_aside()
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")   # lets the email checker and API share the file
        _allow_twilio_channel(conn)
        conn.executescript(SCHEMA)
        # Upgrades for databases created by earlier versions
        _add_column_if_missing(conn, "messages", "reply_address", "TEXT")
        _add_column_if_missing(conn, "messages", "handled_note", "TEXT")      # set when the app dealt with a message itself
        # A customer's answer to one of our replies is stored as a follow-up of the original inquiry
        # (parent_id) instead of becoming a new inquiry of its own.
        _add_column_if_missing(conn, "messages", "parent_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "followup_unread", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "messages", "last_followup_at", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_messages_parent ON messages(parent_id)")
        _add_column_if_missing(conn, "messages", "replied_at", "TEXT")