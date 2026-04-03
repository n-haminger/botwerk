"""Tests for botwerk_bot.webui.auth — password hashing and JWT tokens."""

from __future__ import annotations

import time

import jwt
import pytest

from botwerk_bot.webui.auth import (
    _JWT_ALGORITHM,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from botwerk_bot.webui.schemas import TokenPayload

SECRET = "test-secret-for-auth-long-enough-for-hs256"


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "hunter2-secure"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_different_hashes_for_same_password(self):
        pw = "same-password"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # bcrypt uses random salt
        assert verify_password(pw, h1)
        assert verify_password(pw, h2)


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token(42, True, SECRET)
        payload = decode_token(token, SECRET)
        assert isinstance(payload, TokenPayload)
        assert payload.user_id == 42
        assert payload.is_admin is True
        assert payload.exp > int(time.time())

    def test_non_admin_token(self):
        token = create_access_token(7, False, SECRET)
        payload = decode_token(token, SECRET)
        assert payload.user_id == 7
        assert payload.is_admin is False

    def test_expired_token_raises(self):
        expired_payload = {
            "user_id": 1,
            "is_admin": False,
            "exp": int(time.time()) - 100,
        }
        token = jwt.encode(expired_payload, SECRET, algorithm=_JWT_ALGORITHM)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token, SECRET)

    def test_wrong_secret_raises(self):
        token = create_access_token(1, False, SECRET)
        with pytest.raises(jwt.PyJWTError):
            decode_token(token, "wrong-secret")

    def test_malformed_token_raises(self):
        with pytest.raises(jwt.PyJWTError):
            decode_token("not-a-jwt-at-all", SECRET)

    def test_empty_string_token_raises(self):
        with pytest.raises(jwt.PyJWTError):
            decode_token("", SECRET)

    def test_token_missing_fields_raises(self):
        """A JWT with valid signature but missing required fields."""
        incomplete = jwt.encode({"foo": "bar", "exp": int(time.time()) + 3600}, SECRET, algorithm=_JWT_ALGORITHM)
        with pytest.raises(Exception):
            decode_token(incomplete, SECRET)

    def test_token_payload_types(self):
        token = create_access_token(99, True, SECRET)
        payload = decode_token(token, SECRET)
        assert isinstance(payload.user_id, int)
        assert isinstance(payload.is_admin, bool)
        assert isinstance(payload.exp, int)


class TestGetCurrentUserDependency:
    """Tests for the get_current_user FastAPI dependency factory."""

    @pytest.mark.asyncio
    async def test_missing_cookie_returns_401(self):
        from fastapi import HTTPException

        from botwerk_bot.webui.auth import get_current_user

        dep = get_current_user(SECRET)
        with pytest.raises(HTTPException) as exc_info:
            await dep(botwerk_token=None)
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_expired_cookie_returns_401(self):
        from fastapi import HTTPException

        from botwerk_bot.webui.auth import get_current_user

        expired_payload = {
            "user_id": 1,
            "is_admin": False,
            "exp": int(time.time()) - 100,
        }
        token = jwt.encode(expired_payload, SECRET, algorithm=_JWT_ALGORITHM)
        dep = get_current_user(SECRET)
        with pytest.raises(HTTPException) as exc_info:
            await dep(botwerk_token=token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_cookie_returns_401(self):
        from fastapi import HTTPException

        from botwerk_bot.webui.auth import get_current_user

        dep = get_current_user(SECRET)
        with pytest.raises(HTTPException) as exc_info:
            await dep(botwerk_token="garbage-token")
        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_cookie_returns_payload(self):
        from botwerk_bot.webui.auth import get_current_user

        token = create_access_token(5, True, SECRET)
        dep = get_current_user(SECRET)
        payload = await dep(botwerk_token=token)
        assert payload.user_id == 5
        assert payload.is_admin is True
