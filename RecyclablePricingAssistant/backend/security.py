# security.py - password hashing, login tokens and encryption of saved secrets.
import base64
import hashlib
import hmac
import os
import secrets

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


_dummy_hash = None


def burn_password_time(password: str) -> None:
    """Do the same work as a real check, so unknown emails can't be told apart by timing."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(password, _dummy_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Only this hash is stored, so a leaked database does not leak usable tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_api_key() -> str:
    return "jsk_" + secrets.token_urlsafe(24)


def _fernet():
    secret = os.environ.get("APP_SECRET", "")
    if len(secret) < 16:
        raise RuntimeError("APP_SECRET is not set (or too short). Add a long random value to your .env file.")
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError("The 'cryptography' package is not installed. Run: pip install cryptography")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
