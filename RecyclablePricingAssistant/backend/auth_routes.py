# auth_routes.py - sign up, log in/out, devices, password and staff accounts.
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from backend import account_service
from backend.auth import any_user, owner_only

router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL.match(value):
        raise ValueError("Enter a valid email address")
    return value


class _HasEmail(BaseModel):
    """Base for requests with an email: trims it, lower-cases it and checks its shape."""
    email: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return _clean_email(value)


class RegisterShopRequest(_HasEmail):
    shop_name: str = Field(min_length=2, max_length=100)
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    device_name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(_HasEmail):
    password: str = Field(min_length=1, max_length=128)
    device_name: Optional[str] = Field(default=None, max_length=100)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class StaffCreateRequest(_HasEmail):
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["dispatcher", "driver"]


class StaffUpdateRequest(BaseModel):
    role: Optional[Literal["dispatcher", "driver"]] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


#  sign up / log in
@router.post("/auth/register-shop", status_code=201)
def register_shop(body: RegisterShopRequest):
    """Create a new junkshop and its owner account, and log the owner in."""
    return account_service.register_shop(
        body.shop_name, body.full_name, body.email, body.password, body.device_name)


@router.post("/auth/login")
def login(body: LoginRequest):
    """Log in from any device. Each device gets its own token."""
    return account_service.login(body.email, body.password, body.device_name)


@router.post("/auth/logout")
def logout(user: dict = Depends(any_user)):
    """Log out this device only."""
    account_service.logout(user["token"])
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(user: dict = Depends(any_user)):
    """Log out every device."""
    account_service.logout_all(user["id"])
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(any_user)):
    return account_service.public_user(user)


@router.get("/auth/sessions")
def sessions(user: dict = Depends(any_user)):
    """The devices currently logged in to this account."""
    return {"sessions": account_service.list_sessions(user)}


@router.delete("/auth/sessions/{session_id}")
def revoke_session(session_id: int, user: dict = Depends(any_user)):
    account_service.revoke_session(user, session_id)
    return {"ok": True}


@router.post("/auth/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(any_user)):
    """Changes the password and logs out the other devices."""
    account_service.change_password(user, body.current_password, body.new_password)
    return {"ok": True}


#  staff (owner only)
@router.post("/staff", status_code=201)
def create_staff(body: StaffCreateRequest, owner: dict = Depends(owner_only)):
    """Owner adds a dispatcher or driver with a starting password."""
    return account_service.create_staff(owner, body.full_name, body.email, body.password, body.role)


@router.get("/staff")
def list_staff(owner: dict = Depends(owner_only)):
    return {"staff": account_service.list_staff(owner)}


@router.patch("/staff/{user_id}")
def update_staff(user_id: int, body: StaffUpdateRequest, owner: dict = Depends(owner_only)):
    """Change a role, turn an account off/on, or reset its password."""
    return account_service.update_staff(owner, user_id, body.role, body.is_active, body.new_password)
