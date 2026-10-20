# auth.py - FastAPI "who is calling?" checks, used by every protected endpoint.
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend import account_service
from backend.errors import ApiError

# Shows an "Authorize" button on /docs: log in, then paste the token there.
bearer = HTTPBearer(auto_error=False, description="Log in with POST /auth/login and paste the token.")

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "Not logged in.", _UNAUTHORIZED)
    user = account_service.authenticate_token(credentials.credentials)
    if user is None:
        raise ApiError(401, "Your session has expired or is invalid. Please log in again.", _UNAUTHORIZED)
    user["token"] = credentials.credentials
    return user


def require_roles(*roles: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise ApiError(403, "Your role is not allowed to do this.")
        return user
    return check


# Handy shortcuts
any_user = get_current_user
owner_only = require_roles("owner")
inbox_staff = require_roles("owner", "dispatcher")
