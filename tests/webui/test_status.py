"""Tests for system status API routes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from httpx import AsyncClient

from botwerk_bot.webui.auth import COOKIE_NAME, _JWT_ALGORITHM

from .conftest import TEST_SECRET


def _admin_cookie() -> dict[str, str]:
    """Create an admin JWT cookie for test requests."""
    payload = {
        "user_id": 1,
        "is_admin": True,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    return {COOKIE_NAME: token}


def _non_admin_cookie() -> dict[str, str]:
    """Create a non-admin JWT cookie for test requests."""
    payload = {
        "user_id": 2,
        "is_admin": False,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    return {COOKIE_NAME: token}


@pytest.mark.asyncio
async def test_system_status(client: AsyncClient):
    """System status returns CPU, memory, disk, uptime."""
    mock_cpu = 25.5
    mock_mem = MagicMock()
    mock_mem.total = 16_000_000_000
    mock_mem.used = 8_000_000_000
    mock_mem.available = 8_000_000_000
    mock_mem.percent = 50.0

    mock_disk = MagicMock()
    mock_disk.total = 100_000_000_000
    mock_disk.used = 60_000_000_000
    mock_disk.free = 40_000_000_000
    mock_disk.percent = 60.0

    with (
        patch("botwerk_bot.webui.routes.status_routes.psutil.cpu_percent", return_value=mock_cpu),
        patch(
            "botwerk_bot.webui.routes.status_routes.psutil.virtual_memory",
            return_value=mock_mem,
        ),
        patch("botwerk_bot.webui.routes.status_routes.psutil.disk_usage", return_value=mock_disk),
        patch(
            "botwerk_bot.webui.routes.status_routes.psutil.boot_time",
            return_value=time.time() - 86400,
        ),
        patch("botwerk_bot.webui.routes.status_routes.psutil.cpu_count", return_value=4),
    ):
        resp = await client.get("/api/status/system", cookies=_admin_cookie())

    assert resp.status_code == 200
    data = resp.json()
    assert data["cpu"]["percent"] == 25.5
    assert data["cpu"]["count"] == 4
    assert data["memory"]["percent"] == 50.0
    assert data["disk"]["percent"] == 60.0
    assert data["uptime_seconds"] > 80000


@pytest.mark.asyncio
async def test_system_status_non_admin(client: AsyncClient):
    """Non-admin users are denied."""
    resp = await client.get("/api/status/system", cookies=_non_admin_cookie())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_agent_status_no_agents(client: AsyncClient, tmp_path):
    """Agent status returns empty list when no agents configured."""
    agents_path = tmp_path / "agents_empty.json"
    agents_path.write_text("[]", encoding="utf-8")

    with patch(
        "botwerk_bot.webui.routes.status_routes._DEFAULT_AGENTS_PATH",
        agents_path,
    ):
        resp = await client.get("/api/status/agents", cookies=_admin_cookie())

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_agent_status_with_agents(client: AsyncClient, tmp_path):
    """Agent status returns agent info with process data."""
    agents_path = tmp_path / "agents.json"
    agents_path.write_text(
        json.dumps([
            {"name": "test-agent", "agent_type": "worker", "linux_user_name": "testuser"},
        ]),
        encoding="utf-8",
    )

    # Mock psutil.process_iter to return no matching processes
    with (
        patch(
            "botwerk_bot.webui.routes.status_routes._DEFAULT_AGENTS_PATH",
            agents_path,
        ),
        patch(
            "botwerk_bot.webui.routes.status_routes.psutil.process_iter",
            return_value=[],
        ),
    ):
        resp = await client.get("/api/status/agents", cookies=_admin_cookie())

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "test-agent"
    assert data[0]["status"] == "stopped"
    assert data[0]["linux_user"] == "testuser"


@pytest.mark.asyncio
async def test_service_status(client: AsyncClient):
    """Service status returns systemctl output."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        "botwerk.service - Botwerk Agent Service\n"
        "   Active: active (running) since Mon 2024-01-01 00:00:00 UTC\n"
    )

    with patch(
        "botwerk_bot.webui.routes.status_routes.subprocess.run",
        return_value=mock_result,
    ):
        resp = await client.get("/api/status/service", cookies=_admin_cookie())

    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "botwerk"
    assert "active" in data["active_state"].lower()


@pytest.mark.asyncio
async def test_service_status_systemctl_not_found(client: AsyncClient):
    """Service status handles missing systemctl gracefully."""
    with patch(
        "botwerk_bot.webui.routes.status_routes.subprocess.run",
        side_effect=FileNotFoundError(),
    ):
        resp = await client.get("/api/status/service", cookies=_admin_cookie())

    assert resp.status_code == 200
    data = resp.json()
    assert data["active_state"] == "unknown"


@pytest.mark.asyncio
async def test_restart_agent(client: AsyncClient, tmp_path):
    """Restart agent creates a restart marker file."""
    agents_path = tmp_path / "agents.json"
    agents_path.write_text(
        json.dumps([{"name": "test-agent"}]),
        encoding="utf-8",
    )

    # We need to patch Path.touch on the specific marker path.
    # Instead, just patch _DEFAULT_AGENTS_PATH and let the marker path
    # be created in the real home dir (or mock the touch).
    touched = []

    original_touch = Path.touch

    def mock_touch(self, **kwargs):
        if "restart-" in str(self):
            touched.append(str(self))
            return
        return original_touch(self, **kwargs)

    with (
        patch(
            "botwerk_bot.webui.routes.status_routes._DEFAULT_AGENTS_PATH",
            agents_path,
        ),
        patch.object(Path, "touch", mock_touch),
    ):
        resp = await client.post(
            "/api/status/restart-agent/test-agent",
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "restart_requested"
    assert data["agent"] == "test-agent"
    assert len(touched) == 1
    assert "restart-test-agent" in touched[0]


@pytest.mark.asyncio
async def test_restart_agent_not_found(client: AsyncClient, tmp_path):
    """Restart agent returns 404 for unknown agent."""
    agents_path = tmp_path / "agents.json"
    agents_path.write_text("[]", encoding="utf-8")

    with patch(
        "botwerk_bot.webui.routes.status_routes._DEFAULT_AGENTS_PATH",
        agents_path,
    ):
        resp = await client.post(
            "/api/status/restart-agent/nonexistent",
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restart_botwerk(client: AsyncClient, tmp_path):
    """Restart botwerk touches the restart-requested marker."""
    marker = tmp_path / "restart-requested"

    with patch(
        "botwerk_bot.webui.routes.status_routes._RESTART_MARKER",
        marker,
    ):
        resp = await client.post(
            "/api/status/restart-botwerk",
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "restart_requested"
    assert marker.exists()


@pytest.mark.asyncio
async def test_restart_botwerk_non_admin(client: AsyncClient):
    """Non-admin users cannot restart botwerk."""
    resp = await client.post(
        "/api/status/restart-botwerk",
        cookies=_non_admin_cookie(),
    )
    assert resp.status_code == 403
