"""Tests for WebUI API routes: auth, agents, health."""

from __future__ import annotations

import time

import jwt
import pytest
from httpx import AsyncClient

from botwerk_bot.webui.auth import COOKIE_NAME, _JWT_ALGORITHM

from .conftest import TEST_SECRET


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "webui"


@pytest.mark.asyncio
async def test_setup_first_user(client: AsyncClient):
    resp = await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
        "display_name": "Admin User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "admin"
    assert data["display_name"] == "Admin User"
    assert data["is_admin"] is True


@pytest.mark.asyncio
async def test_setup_rejects_second_user(client: AsyncClient):
    # Create first user
    resp = await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    assert resp.status_code == 201

    # Try to create a second via setup
    resp = await client.post("/api/auth/setup", json={
        "username": "hacker",
        "password": "securepassword456",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_and_me(client: AsyncClient):
    # Setup
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })

    # Login
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "securepassword123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True

    # Extract cookie
    cookies = resp.cookies
    assert "botwerk_token" in cookies

    # Get /me
    resp = await client.get("/api/auth/me", cookies=cookies)
    assert resp.status_code == 200
    me = resp.json()
    assert me["username"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })

    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "username": "nobody",
        "password": "whatever123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_without_auth(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout(client: AsyncClient):
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "securepassword123",
    })
    cookies = resp.cookies

    resp = await client.post("/api/auth/logout", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_agents_empty(client: AsyncClient):
    """Authenticated user with no assignments gets empty list."""
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "securepassword123",
    })
    cookies = resp.cookies

    resp = await client.get("/api/agents", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_agents_without_auth(client: AsyncClient):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401


# -- Setup edge cases --------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_missing_password(client: AsyncClient):
    """Setup with missing password field returns 422."""
    resp = await client.post("/api/auth/setup", json={
        "username": "admin",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_missing_username(client: AsyncClient):
    """Setup with missing username field returns 422."""
    resp = await client.post("/api/auth/setup", json={
        "password": "securepassword123",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_password_too_short(client: AsyncClient):
    """Password shorter than 8 chars must be rejected."""
    resp = await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "short",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_username_too_short(client: AsyncClient):
    """Username shorter than 2 chars must be rejected."""
    resp = await client.post("/api/auth/setup", json={
        "username": "a",
        "password": "securepassword123",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_empty_body(client: AsyncClient):
    """Empty JSON body returns 422."""
    resp = await client.post("/api/auth/setup", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_invalid_json(client: AsyncClient):
    """Non-JSON body returns 422."""
    resp = await client.post(
        "/api/auth/setup",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_setup_no_display_name_uses_username(client: AsyncClient):
    """When display_name is omitted, username is used as fallback."""
    resp = await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["display_name"] == "admin"


# -- Login edge cases --------------------------------------------------------


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient):
    """Login without required fields returns 422."""
    resp = await client.post("/api/auth/login", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_json(client: AsyncClient):
    """Login with non-JSON body returns 422."""
    resp = await client.post(
        "/api/auth/login",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_updates_last_login(client: AsyncClient):
    """After login, last_login should be set."""
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "securepassword123",
    })
    assert resp.status_code == 200

    # Use the cookie from login to check /me
    token_cookie = resp.cookies.get(COOKIE_NAME)
    client.cookies.set(COOKIE_NAME, token_cookie)
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["last_login"] is not None
    client.cookies.clear()


# -- /me edge cases ----------------------------------------------------------


@pytest.mark.asyncio
async def test_me_with_expired_token(client: AsyncClient):
    """Expired JWT cookie returns 401."""
    expired_payload = {
        "user_id": 1,
        "is_admin": False,
        "exp": int(time.time()) - 100,
    }
    token = jwt.encode(expired_payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    client.cookies.clear()


@pytest.mark.asyncio
async def test_me_with_malformed_token(client: AsyncClient):
    """Garbage JWT cookie returns 401."""
    client.cookies.set(COOKIE_NAME, "garbage-not-a-jwt")
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    client.cookies.clear()


@pytest.mark.asyncio
async def test_me_with_wrong_secret_token(client: AsyncClient):
    """Token signed with a different secret returns 401."""
    token = jwt.encode(
        {"user_id": 1, "is_admin": False, "exp": int(time.time()) + 3600},
        "completely-different-secret-key-long-enough",
        algorithm=_JWT_ALGORITHM,
    )
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    client.cookies.clear()


@pytest.mark.asyncio
async def test_me_with_deleted_user(client: AsyncClient, db_session):
    """Valid token for a user that no longer exists returns 404."""
    from botwerk_bot.webui.auth import create_access_token
    from botwerk_bot.webui.models import User

    # Create and then delete a user directly.
    user = User(username="ephemeral", password_hash="hash", display_name="Gone", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user.id, False, TEST_SECRET)

    await db_session.delete(user)
    await db_session.commit()

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 404
    client.cookies.clear()


# -- Logout edge cases -------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_without_auth(client: AsyncClient):
    """Logout without being logged in should still return 200."""
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200


# -- Agents with data --------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_with_assignments(
    client: AsyncClient, db_session, _test_agents_json
):
    """Admin user sees agents from agents.json; non-admin sees DB assignments."""
    import json
    from botwerk_bot.webui.models import AgentAssignment, User
    from botwerk_bot.webui.auth import hash_password

    # Write agents to the test agents.json.
    _test_agents_json.write_text(
        json.dumps([{"name": "main"}, {"name": "helper"}]),
        encoding="utf-8",
    )

    # Setup admin and login.
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "securepassword123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "securepassword123",
    })
    token_cookie = resp.cookies.get(COOKIE_NAME)

    # Admin sees all agents from agents.json.
    client.cookies.set(COOKIE_NAME, token_cookie)
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    names = {a["name"] for a in agents}
    assert names == {"main", "helper"}
    client.cookies.clear()
