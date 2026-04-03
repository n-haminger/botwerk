"""Tests for Agent CRUD API routes (Phase 4)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from httpx import AsyncClient

from botwerk_bot.webui.auth import COOKIE_NAME, _JWT_ALGORITHM

from .conftest import TEST_SECRET


def _make_cookie(user_id: int = 1, is_admin: bool = True) -> dict[str, str]:
    """Build a JWT cookie for test requests."""
    payload = {
        "user_id": user_id,
        "is_admin": is_admin,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    return {COOKIE_NAME: token}


def _setup_agents_json(tmp_path: Path, agents: list[dict] | None = None) -> Path:
    """Create an agents.json file and patch the default path."""
    path = tmp_path / "agents.json"
    data = agents or []
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def agents_path(tmp_path):
    """Create a temporary agents.json and patch the route to use it."""
    path = _setup_agents_json(tmp_path, [])
    with patch(
        "botwerk_bot.webui.routes.agent_routes._get_agents_path",
        return_value=path,
    ):
        yield path


@pytest.fixture
def agents_path_with_data(tmp_path):
    """Create a temporary agents.json with some agents and patch the route."""
    agents = [
        {
            "name": "worker-1",
            "provider": "claude",
            "model": "claude-sonnet-4-20250514",
            "agent_type": "worker",
            "trust_level": "restricted",
            "agent_secret": "secret1",
        },
        {
            "name": "manager-1",
            "provider": "claude",
            "model": "claude-sonnet-4-20250514",
            "agent_type": "management",
            "trust_level": "privileged",
            "agent_secret": "secret2",
            "workers": ["worker-1"],
        },
    ]
    path = _setup_agents_json(tmp_path, agents)
    with patch(
        "botwerk_bot.webui.routes.agent_routes._get_agents_path",
        return_value=path,
    ):
        yield path


# -- List agents ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_admin(client: AsyncClient, agents_path_with_data: Path):
    """Admin sees all agents."""
    resp = await client.get("/api/agents", cookies=_make_cookie(is_admin=True))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {a["name"] for a in data}
    assert names == {"worker-1", "manager-1"}


@pytest.mark.asyncio
async def test_list_agents_non_admin_sees_assigned(
    client: AsyncClient, agents_path_with_data: Path, db_session
):
    """Non-admin user only sees agents assigned to them."""
    from botwerk_bot.webui.models import AgentAssignment, User
    from botwerk_bot.webui.auth import hash_password

    # Create a non-admin user
    user = User(username="regular", password_hash=hash_password("password"), is_admin=False)
    db_session.add(user)
    await db_session.flush()

    # Assign only worker-1
    assignment = AgentAssignment(user_id=user.id, agent_name="worker-1")
    db_session.add(assignment)
    await db_session.commit()

    resp = await client.get(
        "/api/agents",
        cookies=_make_cookie(user_id=user.id, is_admin=False),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "worker-1"


# -- Create agent --------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent(client: AsyncClient, agents_path: Path):
    """Admin can create a new agent."""
    resp = await client.post(
        "/api/agents",
        json={"name": "test-agent", "provider": "claude", "model": "claude-sonnet-4-20250514"},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-agent"
    assert data["provider"] == "claude"

    # Verify persisted
    raw = json.loads(agents_path.read_text())
    assert len(raw) == 1
    assert raw[0]["name"] == "test-agent"


@pytest.mark.asyncio
async def test_create_agent_duplicate(client: AsyncClient, agents_path_with_data: Path):
    """Creating an agent with an existing name returns 409."""
    resp = await client.post(
        "/api/agents",
        json={"name": "worker-1"},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_agent_reserved_name(client: AsyncClient, agents_path: Path):
    """Creating an agent named 'main' is rejected."""
    resp = await client.post(
        "/api/agents",
        json={"name": "main"},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_agent_non_admin_rejected(client: AsyncClient, agents_path: Path):
    """Non-admin cannot create agents."""
    resp = await client.post(
        "/api/agents",
        json={"name": "test-agent"},
        cookies=_make_cookie(is_admin=False),
    )
    assert resp.status_code == 403


# -- Update agent --------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_agent(client: AsyncClient, agents_path_with_data: Path):
    """Admin can update an agent."""
    resp = await client.put(
        "/api/agents/worker-1",
        json={"model": "claude-opus-4-20250514"},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "claude-opus-4-20250514"

    # Verify persisted
    raw = json.loads(agents_path_with_data.read_text())
    match = next(a for a in raw if a["name"] == "worker-1")
    assert match["model"] == "claude-opus-4-20250514"


@pytest.mark.asyncio
async def test_update_agent_not_found(client: AsyncClient, agents_path: Path):
    """Updating a non-existent agent returns 404."""
    resp = await client.put(
        "/api/agents/nonexistent",
        json={"model": "test"},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_agent_non_admin_rejected(
    client: AsyncClient, agents_path_with_data: Path
):
    """Non-admin cannot update agents."""
    resp = await client.put(
        "/api/agents/worker-1",
        json={"model": "test"},
        cookies=_make_cookie(is_admin=False),
    )
    assert resp.status_code == 403


# -- Delete agent --------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent(client: AsyncClient, agents_path_with_data: Path):
    """Admin can delete an agent."""
    resp = await client.delete(
        "/api/agents/worker-1",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 204

    raw = json.loads(agents_path_with_data.read_text())
    names = {a["name"] for a in raw}
    assert "worker-1" not in names


@pytest.mark.asyncio
async def test_delete_agent_not_found(client: AsyncClient, agents_path: Path):
    """Deleting a non-existent agent returns 404."""
    resp = await client.delete(
        "/api/agents/nonexistent",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent_non_admin_rejected(
    client: AsyncClient, agents_path_with_data: Path
):
    """Non-admin cannot delete agents."""
    resp = await client.delete(
        "/api/agents/worker-1",
        cookies=_make_cookie(is_admin=False),
    )
    assert resp.status_code == 403


# -- Start / Stop (placeholders) -----------------------------------------------


@pytest.mark.asyncio
async def test_start_agent(client: AsyncClient, agents_path_with_data: Path):
    """Start returns a status message."""
    resp = await client.post(
        "/api/agents/worker-1/start",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "start_requested"


@pytest.mark.asyncio
async def test_stop_agent(client: AsyncClient, agents_path_with_data: Path):
    """Stop returns a status message."""
    resp = await client.post(
        "/api/agents/worker-1/stop",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "stop_requested"


# -- Hierarchy -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_hierarchy(client: AsyncClient, agents_path_with_data: Path):
    """Admin can set hierarchy on an agent."""
    resp = await client.put(
        "/api/agents/manager-1/hierarchy",
        json={"workers": ["worker-1"]},
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workers"] == ["worker-1"]


@pytest.mark.asyncio
async def test_get_hierarchy_tree(client: AsyncClient, agents_path_with_data: Path):
    """Get hierarchy tree returns a valid structure."""
    resp = await client.get(
        "/api/agents/hierarchy/tree",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "roots" in data


# -- Permission templates ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient, agents_path: Path):
    """List permission templates returns the three built-in templates."""
    resp = await client.get(
        "/api/agents/templates/list",
        cookies=_make_cookie(is_admin=True),
    )
    assert resp.status_code == 200
    data = resp.json()
    names = {t["name"] for t in data}
    assert names == {"developer", "ops", "restricted"}


@pytest.mark.asyncio
async def test_list_templates_non_admin_rejected(client: AsyncClient, agents_path: Path):
    """Non-admin cannot list templates."""
    resp = await client.get(
        "/api/agents/templates/list",
        cookies=_make_cookie(is_admin=False),
    )
    assert resp.status_code == 403
