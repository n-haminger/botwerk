"""Tests for admin API routes: config, users, cron."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from botwerk_bot.webui.auth import COOKIE_NAME, create_access_token, hash_password
from botwerk_bot.webui.models import AgentAssignment, User

from .conftest import TEST_SECRET


# -- Helpers -------------------------------------------------------------------


async def _setup_admin(client: AsyncClient) -> dict:
    """Create admin user and return login cookies."""
    await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "securepassword123"},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "securepassword123"},
    )
    return dict(resp.cookies)


async def _create_non_admin(db_session, *, username: str = "viewer") -> User:
    """Create a non-admin user directly in the DB."""
    user = User(
        username=username,
        password_hash=hash_password("viewerpassword123"),
        display_name=username.title(),
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _non_admin_cookies(user_id: int) -> dict:
    """Create a JWT cookie dict for a non-admin user."""
    token = create_access_token(user_id, False, TEST_SECRET)
    return {COOKIE_NAME: token}


# =============================================================================
# Config routes
# =============================================================================


@pytest.mark.asyncio
async def test_config_get(client: AsyncClient, _test_config_json):
    """Admin can read config; secrets are masked."""
    cookies = await _setup_admin(client)

    resp = await client.get("/api/admin/config", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    config = data["config"]
    assert config["provider"] == "claude"
    # Secret fields should be masked.
    assert config["webui"]["secret_key"] == "********"
    assert config["api"]["token"] == "********"


@pytest.mark.asyncio
async def test_config_get_non_admin(client: AsyncClient, db_session, _test_config_json):
    """Non-admin is rejected from config endpoint."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    resp = await client.get("/api/admin/config", cookies=cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_config_get_unauthenticated(client: AsyncClient, _test_config_json):
    """Unauthenticated request is rejected."""
    resp = await client.get("/api/admin/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_config_update(client: AsyncClient, _test_config_json):
    """Admin can update config values."""
    cookies = await _setup_admin(client)

    resp = await client.put(
        "/api/admin/config",
        json={"log_level": "DEBUG"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["config"]["log_level"] == "DEBUG"

    # Verify it was persisted.
    raw = json.loads(_test_config_json.read_text(encoding="utf-8"))
    assert raw["log_level"] == "DEBUG"


@pytest.mark.asyncio
async def test_config_update_rejects_masked_values(client: AsyncClient, _test_config_json):
    """Submitting masked values (********) is rejected."""
    cookies = await _setup_admin(client)

    resp = await client.put(
        "/api/admin/config",
        json={"webui": {"secret_key": "********"}},
        cookies=cookies,
    )
    assert resp.status_code == 422
    assert "Masked value" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_config_update_invalid_value(client: AsyncClient, _test_config_json):
    """Invalid config values are rejected during validation."""
    cookies = await _setup_admin(client)

    resp = await client.put(
        "/api/admin/config",
        json={"streaming": "not-an-object"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_config_update_non_admin(client: AsyncClient, db_session, _test_config_json):
    """Non-admin cannot update config."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    resp = await client.put(
        "/api/admin/config",
        json={"log_level": "DEBUG"},
        cookies=cookies,
    )
    assert resp.status_code == 403


# =============================================================================
# User management routes
# =============================================================================


@pytest.mark.asyncio
async def test_users_list(client: AsyncClient):
    """Admin can list all users."""
    cookies = await _setup_admin(client)

    resp = await client.get("/api/admin/users", cookies=cookies)
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"


@pytest.mark.asyncio
async def test_users_list_non_admin(client: AsyncClient, db_session):
    """Non-admin is rejected from users list."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    resp = await client.get("/api/admin/users", cookies=cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_users_create(client: AsyncClient):
    """Admin can create a new user."""
    cookies = await _setup_admin(client)

    resp = await client.post(
        "/api/admin/users",
        json={
            "username": "newuser",
            "password": "newpassword123",
            "display_name": "New User",
            "is_admin": False,
        },
        cookies=cookies,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["display_name"] == "New User"
    assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_users_create_duplicate(client: AsyncClient):
    """Creating a user with a duplicate username is rejected."""
    cookies = await _setup_admin(client)

    await client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "password1234"},
        cookies=cookies,
    )
    resp = await client.post(
        "/api/admin/users",
        json={"username": "dup", "password": "password5678"},
        cookies=cookies,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_users_update(client: AsyncClient):
    """Admin can update another user."""
    cookies = await _setup_admin(client)

    # Create a user.
    resp = await client.post(
        "/api/admin/users",
        json={"username": "target", "password": "targetpass123"},
        cookies=cookies,
    )
    user_id = resp.json()["id"]

    # Update display name.
    resp = await client.put(
        f"/api/admin/users/{user_id}",
        json={"display_name": "Updated Name"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_users_self_update(client: AsyncClient, db_session):
    """Non-admin can update own password and display_name but not is_admin."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    # Can update display_name.
    resp = await client.put(
        f"/api/admin/users/{user.id}",
        json={"display_name": "My New Name"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "My New Name"

    # Cannot change is_admin.
    resp = await client.put(
        f"/api/admin/users/{user.id}",
        json={"is_admin": True},
        cookies=cookies,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_users_delete(client: AsyncClient):
    """Admin can delete another user."""
    cookies = await _setup_admin(client)

    resp = await client.post(
        "/api/admin/users",
        json={"username": "deleteme", "password": "deletepass123"},
        cookies=cookies,
    )
    user_id = resp.json()["id"]

    resp = await client.delete(f"/api/admin/users/{user_id}", cookies=cookies)
    assert resp.status_code == 204

    # Verify user is gone.
    resp = await client.get("/api/admin/users", cookies=cookies)
    assert all(u["id"] != user_id for u in resp.json())


@pytest.mark.asyncio
async def test_users_cannot_delete_self(client: AsyncClient):
    """Admin cannot delete themselves."""
    cookies = await _setup_admin(client)

    # Get own user id.
    resp = await client.get("/api/auth/me", cookies=cookies)
    my_id = resp.json()["id"]

    resp = await client.delete(f"/api/admin/users/{my_id}", cookies=cookies)
    assert resp.status_code == 400
    assert "yourself" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_users_delete_nonexistent(client: AsyncClient):
    """Deleting a nonexistent user returns 404."""
    cookies = await _setup_admin(client)

    resp = await client.delete("/api/admin/users/99999", cookies=cookies)
    assert resp.status_code == 404


# =============================================================================
# Agent assignments
# =============================================================================


@pytest.mark.asyncio
async def test_agent_assignments(client: AsyncClient):
    """Admin can set and get agent assignments for a user."""
    cookies = await _setup_admin(client)

    # Create a user.
    resp = await client.post(
        "/api/admin/users",
        json={"username": "worker", "password": "workerpass123"},
        cookies=cookies,
    )
    user_id = resp.json()["id"]

    # Set assignments.
    resp = await client.put(
        f"/api/admin/users/{user_id}/agents",
        json={"agent_names": ["main", "helper"]},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert set(resp.json()["agent_names"]) == {"main", "helper"}

    # Get assignments.
    resp = await client.get(f"/api/admin/users/{user_id}/agents", cookies=cookies)
    assert resp.status_code == 200
    assert set(resp.json()["agent_names"]) == {"main", "helper"}

    # Update assignments (replace).
    resp = await client.put(
        f"/api/admin/users/{user_id}/agents",
        json={"agent_names": ["main"]},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["agent_names"] == ["main"]


@pytest.mark.asyncio
async def test_agent_assignments_nonexistent_user(client: AsyncClient):
    """Agent assignments for nonexistent user returns 404."""
    cookies = await _setup_admin(client)

    resp = await client.get("/api/admin/users/99999/agents", cookies=cookies)
    assert resp.status_code == 404

    resp = await client.put(
        "/api/admin/users/99999/agents",
        json={"agent_names": ["main"]},
        cookies=cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_assignments_non_admin(client: AsyncClient, db_session):
    """Non-admin cannot manage agent assignments."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    resp = await client.get(f"/api/admin/users/{user.id}/agents", cookies=cookies)
    assert resp.status_code == 403


# =============================================================================
# Cron routes
# =============================================================================


@pytest.mark.asyncio
async def test_cron_list(client: AsyncClient, _test_cron_json):
    """Admin can list cron jobs."""
    cookies = await _setup_admin(client)

    resp = await client.get("/api/admin/cron", cookies=cookies)
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2
    assert jobs[0]["id"] == "test-job-1"
    assert jobs[0]["enabled"] is True
    assert jobs[0]["next_run"] is not None  # enabled job has next_run
    assert jobs[1]["id"] == "test-job-2"
    assert jobs[1]["enabled"] is False
    assert jobs[1]["next_run"] is None  # disabled job has no next_run


@pytest.mark.asyncio
async def test_cron_list_non_admin(client: AsyncClient, db_session, _test_cron_json):
    """Non-admin is rejected from cron list."""
    await _setup_admin(client)
    user = await _create_non_admin(db_session)
    cookies = _non_admin_cookies(user.id)

    resp = await client.get("/api/admin/cron", cookies=cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cron_enable(client: AsyncClient, _test_cron_json):
    """Admin can enable a disabled cron job."""
    cookies = await _setup_admin(client)

    resp = await client.post("/api/admin/cron/test-job-2/enable", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True

    # Verify persisted.
    raw = json.loads(_test_cron_json.read_text(encoding="utf-8"))
    job2 = next(j for j in raw["jobs"] if j["id"] == "test-job-2")
    assert job2["enabled"] is True


@pytest.mark.asyncio
async def test_cron_disable(client: AsyncClient, _test_cron_json):
    """Admin can disable an enabled cron job."""
    cookies = await _setup_admin(client)

    resp = await client.post("/api/admin/cron/test-job-1/disable", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Verify persisted.
    raw = json.loads(_test_cron_json.read_text(encoding="utf-8"))
    job1 = next(j for j in raw["jobs"] if j["id"] == "test-job-1")
    assert job1["enabled"] is False


@pytest.mark.asyncio
async def test_cron_trigger(client: AsyncClient, _test_cron_json):
    """Admin can trigger a cron job."""
    cookies = await _setup_admin(client)

    resp = await client.post("/api/admin/cron/test-job-1/trigger", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["triggered"] is True


@pytest.mark.asyncio
async def test_cron_not_found(client: AsyncClient, _test_cron_json):
    """Operations on nonexistent cron job return 404."""
    cookies = await _setup_admin(client)

    for action in ("enable", "disable", "trigger"):
        resp = await client.post(f"/api/admin/cron/nonexistent/{action}", cookies=cookies)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cron_unauthenticated(client: AsyncClient, _test_cron_json):
    """Unauthenticated request to cron endpoint is rejected."""
    resp = await client.get("/api/admin/cron")
    assert resp.status_code == 401
