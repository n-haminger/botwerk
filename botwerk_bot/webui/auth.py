"""Authentication utilities for the WebUI: password hashing, JWT tokens, FastAPI deps."""

from __future__ import annotations

import time

import bcrypt
import jwt
from fastapi import Cookie, HTTPException, status

from botwerk_bot.webui.schemas import TokenPayload

# JWT defaults
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_SECONDS = 86400  # 24 hours

COOKIE_NAME = "botwerk_token"


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int, is_admin: bool, secret: str) -> str:
    """Create a signed JWT containing user_id and is_admin."""
    payload = {
        "user_id": user_id,
        "is_admin": is_admin,
        "exp": int(time.time()) + _JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def decode_token(token: str, secret: str) -> TokenPayload:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on failure."""
    data = jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
    return TokenPayload(**data)


def get_current_user(secret: str):  # noqa: ANN201
    """Return a FastAPI dependency that reads the JWT from an HTTP-only cookie.

    Usage::

        app.dependency_overrides[_dep] = ...
        # or inject via Depends(get_current_user(secret_key))
    """

    async def _dependency(
        botwerk_token: str | None = Cookie(None, alias=COOKIE_NAME),
    ) -> TokenPayload:
        if botwerk_token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        try:
            return decode_token(botwerk_token, secret)
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            ) from exc
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from exc

    return _dependency
