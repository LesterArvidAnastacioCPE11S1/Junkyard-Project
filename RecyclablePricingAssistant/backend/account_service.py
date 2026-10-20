# account_service.py - registration, login, device sessions and staff management.
# Plain Python: every problem is raised as an ApiError so the routes stay thin.
import os
from datetime import datetime, timedelta, timezone

from backend import accounts_db, security
from backend.errors import ApiError

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
STAFF_ROLES = ("dispatcher", "driver")


def _now():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.isoformat(timespec="seconds")


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "shop_id": user["shop_id"],
        "is_active": bool(user["is_active"]),
    }


def _start_session(user, shop, device_name):
    token = security.new_token()
    days = int(os.environ.get("TOKEN_DAYS", "30") or 30)
    expires_at = _iso(_now() + timedelta(days=days))
    accounts_db.create_session(user["id"], security.token_hash(token),
                               (device_name or "Unknown device")[:100], expires_at)
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": public_user(user),
        "shop": {"id": shop["id"], "name": shop["name"]},
    }


# sign up / log in
def register_shop(shop_name, full_name, email, password, device_name=None):
    if os.environ.get("ALLOW_SIGNUP", "1").strip().lower() in ("0", "false", "no", "off"):
        raise ApiError(403, "Sign-up is turned off on this server.")
    try:
        shop, user = accounts_db.create_shop_with_owner(
            shop_name.strip(), email, security.hash_password(password), full_name.strip())
    except accounts_db.EmailTaken:
        raise ApiError(409, "An account with that email already exists.")
    return _start_session(user, shop, device_name)


def login(email, password, device_name=None):
    since = _iso(_now() - timedelta(minutes=LOCKOUT_MINUTES))
    if accounts_db.count_recent_failures(email, since) >= MAX_FAILED_LOGINS:
        raise ApiError(429, f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.")

    user = accounts_db.get_user_by_email(email)
    if user is None:
        security.burn_password_time(password)
        ok = False
    else:
        ok = security.verify_password(password, user["password_hash"])

    if not ok:
        accounts_db.record_attempt(email, False)
        raise ApiError(401, "Incorrect email or password.")
    if not user["is_active"]:
        raise ApiError(403, "This account has been turned off. Ask the shop owner.")

    accounts_db.clear_failures(email)
    shop = accounts_db.get_shop(user["shop_id"])
    return _start_session(user, shop, device_name)


#  tokens
def authenticate_token(token: str):
    """Return the logged-in user (plus session_id) or None if the token is not valid."""
    row = accounts_db.get_session_with_user(security.token_hash(token))
    if row is None:
        return None
    if row["expires_at"] <= _iso(_now()):
        accounts_db.delete_session_by_hash(security.token_hash(token))
        return None
    if not row["is_active"]:
        return None
    if row["last_used_at"] <= _iso(_now() - timedelta(minutes=1)):   # avoid a write on every request
        accounts_db.touch_session(row["session_id"])
    return row


def logout(token: str):
    accounts_db.delete_session_by_hash(security.token_hash(token))


def logout_all(user_id: int):
    accounts_db.delete_user_sessions(user_id)


def list_sessions(user: dict):
    sessions = accounts_db.list_sessions(user["id"])
    for session in sessions:
        session["current"] = session["id"] == user["session_id"]
    return sessions


def revoke_session(user: dict, session_id: int):
    if not accounts_db.delete_session_id(user["id"], session_id):
        raise ApiError(404, "Session not found.")


def change_password(user: dict, current_password: str, new_password: str):
    stored = accounts_db.get_user(user["id"])
    if not security.verify_password(current_password, stored["password_hash"]):
        raise ApiError(400, "Current password is incorrect.")
    accounts_db.update_user(user["id"], password_hash=security.hash_password(new_password))
    accounts_db.delete_user_sessions(user["id"], except_session_id=user["session_id"])


#  staff (owner only)
def create_staff(owner: dict, full_name, email, password, role):
    if role not in STAFF_ROLES:
        raise ApiError(400, f"Role must be one of: {', '.join(STAFF_ROLES)}.")
    try:
        user = accounts_db.create_user(owner["shop_id"], email, security.hash_password(password),
                                       full_name.strip(), role)
    except accounts_db.EmailTaken:
        raise ApiError(409, "An account with that email already exists.")
    return public_user(user)


def list_staff(owner: dict):
    return [public_user(u) for u in accounts_db.list_users(owner["shop_id"])]


def update_staff(owner: dict, user_id: int, role=None, is_active=None, new_password=None):
    target = accounts_db.get_user(user_id)
    if target is None or target["shop_id"] != owner["shop_id"]:
        raise ApiError(404, "Staff member not found.")
    if target["role"] == "owner":
        raise ApiError(400, "The owner account can't be changed here.")
    if role is not None and role not in STAFF_ROLES:
        raise ApiError(400, f"Role must be one of: {', '.join(STAFF_ROLES)}.")

    updated = accounts_db.update_user(
        user_id, role=role, is_active=is_active,
        password_hash=security.hash_password(new_password) if new_password else None,
    )
    if is_active is False or new_password:
        accounts_db.delete_user_sessions(user_id)     # sign them out everywhere
    return public_user(updated)
