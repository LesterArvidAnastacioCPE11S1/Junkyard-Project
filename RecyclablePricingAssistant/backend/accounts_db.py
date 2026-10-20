# accounts_db.py - shops, users, login sessions and channel connections (SQLite).
import json
import sqlite3

from backend.db import connect, now_iso


class EmailTaken(Exception):
    pass


class ChannelRefTaken(Exception):
    pass


def _dict(row):
    return dict(row) if row is not None else None


# ---------------------------------------------------------------- shops and users
def create_shop_with_owner(shop_name, email, password_hash, full_name):
    try:
        with connect() as conn:
            shop_id = conn.execute(
                "INSERT INTO shops (name, created_at) VALUES (?, ?)", (shop_name, now_iso())
            ).lastrowid
            user_id = conn.execute(
                """INSERT INTO users (shop_id, email, password_hash, full_name, role, is_active, created_at)
                   VALUES (?, ?, ?, ?, 'owner', 1, ?)""",
                (shop_id, email, password_hash, full_name, now_iso()),
            ).lastrowid
    except sqlite3.IntegrityError:
        raise EmailTaken()
    return get_shop(shop_id), get_user(user_id)


def create_user(shop_id, email, password_hash, full_name, role):
    try:
        with connect() as conn:
            user_id = conn.execute(
                """INSERT INTO users (shop_id, email, password_hash, full_name, role, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (shop_id, email, password_hash, full_name, role, now_iso()),
            ).lastrowid
    except sqlite3.IntegrityError:
        raise EmailTaken()
    return get_user(user_id)


def get_shop(shop_id):
    with connect() as conn:
        return _dict(conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone())


def get_user(user_id):
    with connect() as conn:
        return _dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_email(email):
    with connect() as conn:
        return _dict(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())


def list_users(shop_id):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users WHERE shop_id = ? ORDER BY id", (shop_id,)).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    allowed = {"role", "is_active", "password_hash"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return get_user(user_id)
    if "is_active" in fields:
        fields["is_active"] = int(fields["is_active"])
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connect() as conn:
        conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*fields.values(), user_id))
    return get_user(user_id)


# ---------------------------------------------------------------- sessions (one per device)
def create_session(user_id, token_hash, device_name, expires_at):
    with connect() as conn:
        conn.execute(
            """INSERT INTO sessions (user_id, token_hash, device_name, created_at, last_used_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, token_hash, device_name, now_iso(), now_iso(), expires_at),
        )


def get_session_with_user(token_hash):
    with connect() as conn:
        return _dict(conn.execute(
            """SELECT s.id AS session_id, s.expires_at, s.last_used_at,
                      u.id, u.shop_id, u.email, u.full_name, u.role, u.is_active
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ?""",
            (token_hash,),
        ).fetchone())


def touch_session(session_id):
    with connect() as conn:
        conn.execute("UPDATE sessions SET last_used_at = ? WHERE id = ?", (now_iso(), session_id))


def delete_session_by_hash(token_hash):
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id, except_session_id=None):
    with connect() as conn:
        if except_session_id is None:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, except_session_id))


def list_sessions(user_id):
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, device_name, created_at, last_used_at, expires_at
               FROM sessions WHERE user_id = ? ORDER BY last_used_at DESC""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session_id(user_id, session_id) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        return cur.rowcount > 0


def purge_expired_sessions():
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),))


# ---------------------------------------------------------------- login attempts
def record_attempt(email, success):
    with connect() as conn:
        conn.execute("INSERT INTO login_attempts (email, success, at) VALUES (?, ?, ?)",
                     (email, int(success), now_iso()))


def count_recent_failures(email, since_iso):
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE email = ? AND success = 0 AND at >= ?",
            (email, since_iso),
        ).fetchone()[0]


def clear_failures(email):
    with connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))


def purge_old_attempts(before_iso):
    with connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE at < ?", (before_iso,))


# ---------------------------------------------------------------- channel connections
def _connection(row):
    if row is None:
        return None
    record = dict(row)
    record["config"] = json.loads(record.pop("config_json") or "{}")
    return record


def get_connection(shop_id, channel):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM channel_connections WHERE shop_id = ? AND channel = ?", (shop_id, channel)
        ).fetchone()
    return _connection(row)


def list_connections(shop_id):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM channel_connections WHERE shop_id = ?", (shop_id,)).fetchall()
    return [_connection(r) for r in rows]


def list_connections_by_channel(channel):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM channel_connections WHERE channel = ?", (channel,)).fetchall()
    return [_connection(r) for r in rows]


def find_connection_by_ref(channel, external_ref):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM channel_connections WHERE channel = ? AND external_ref = ?",
            (channel, external_ref),
        ).fetchone()
    return _connection(row)


def upsert_connection(shop_id, channel, external_ref=None, config=None,
                      secret_enc=None, secret_hash=None, secret_hint=None):
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO channel_connections
                   (shop_id, channel, external_ref, config_json, secret_enc, secret_hash, secret_hint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(shop_id, channel) DO UPDATE SET
                     external_ref = excluded.external_ref, config_json = excluded.config_json,
                     secret_enc = excluded.secret_enc, secret_hash = excluded.secret_hash,
                     secret_hint = excluded.secret_hint, last_error = NULL, last_checked_at = NULL""",
                (shop_id, channel, external_ref,
                 json.dumps(config) if config is not None else None,
                 secret_enc, secret_hash, secret_hint, now_iso()),
            )
    except sqlite3.IntegrityError:
        raise ChannelRefTaken()


def delete_connection(shop_id, channel) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM channel_connections WHERE shop_id = ? AND channel = ?",
                           (shop_id, channel))
        return cur.rowcount > 0


def set_check_result(shop_id, channel, error=None):
    with connect() as conn:
        conn.execute(
            """UPDATE channel_connections SET last_checked_at = ?, last_error = ?
               WHERE shop_id = ? AND channel = ?""",
            (now_iso(), error, shop_id, channel),
        )
