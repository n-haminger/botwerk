"""Tests for multiagent/internal_api.py: InternalAgentAPI HTTP endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from botwerk_bot.multiagent.bus import InterAgentBus
from botwerk_bot.multiagent.health import AgentHealth
from botwerk_bot.multiagent.internal_api import InternalAgentAPI


@pytest.fixture
def bus() -> InterAgentBus:
    return InterAgentBus()


@pytest.fixture
def api(bus: InterAgentBus) -> InternalAgentAPI:
    return InternalAgentAPI(bus, port=0)


@pytest.fixture
async def client(api: InternalAgentAPI):
    """Create httpx async client for the internal API."""
    transport = ASGITransport(app=api._app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHandleSend:
    """Test POST /interagent/send."""

    async def test_send_success(self, client: AsyncClient, bus: InterAgentBus) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["text"] == "OK"

    async def test_send_missing_fields(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/interagent/send",
            json={"from": "sender"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "Missing" in data["error"]

    async def test_send_invalid_json(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/interagent/send",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_send_unknown_recipient(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "nonexistent", "message": "Hello"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "not found" in data["error"]


class TestHandleSendAsync:
    """Test POST /interagent/send_async."""

    async def test_send_async_success(self, client: AsyncClient, bus: InterAgentBus) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task_id" in data

    async def test_send_async_unknown_recipient(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender", "to": "nonexistent", "message": "Hello"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "not found" in data["error"]

    async def test_send_async_missing_fields(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender"},
        )
        assert resp.status_code == 400


class TestNewSessionFlag:
    """Test new_session flag in /interagent/send and /interagent/send_async."""

    async def test_send_passes_new_session_true(
        self, client: AsyncClient, bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={
                "from": "sender",
                "to": "target",
                "message": "Hello",
                "new_session": True,
            },
        )
        assert resp.status_code == 200
        stack.bot.orchestrator.handle_interagent_message.assert_awaited_once_with(
            "sender",
            "Hello",
            new_session=True,
        )

    async def test_send_defaults_new_session_false(
        self, client: AsyncClient, bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status_code == 200
        stack.bot.orchestrator.handle_interagent_message.assert_awaited_once_with(
            "sender",
            "Hello",
            new_session=False,
        )

    async def test_send_async_passes_new_session(
        self, client: AsyncClient, bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send_async",
            json={
                "from": "sender",
                "to": "target",
                "message": "Hello",
                "new_session": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestHandleList:
    """Test GET /interagent/agents."""

    async def test_list_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/interagent/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == []

    async def test_list_with_agents(self, client: AsyncClient, bus: InterAgentBus) -> None:
        bus.register("main", MagicMock())
        bus.register("sub1", MagicMock())

        resp = await client.get("/interagent/agents")
        data = resp.json()
        assert set(data["agents"]) == {"main", "sub1"}


class TestHandleHealth:
    """Test GET /interagent/health."""

    async def test_health_no_ref(self, client: AsyncClient) -> None:
        resp = await client.get("/interagent/health")
        data = resp.json()
        assert data["agents"] == {}

    async def test_health_with_agents(self, client: AsyncClient, api: InternalAgentAPI) -> None:
        h = AgentHealth(name="main")
        h.mark_running()
        api.set_health_ref({"main": h})

        resp = await client.get("/interagent/health")
        data = resp.json()
        assert "main" in data["agents"]
        assert data["agents"]["main"]["status"] == "running"
        assert data["agents"]["main"]["restart_count"] == 0

    async def test_health_crashed_agent(self, client: AsyncClient, api: InternalAgentAPI) -> None:
        h = AgentHealth(name="sub1")
        h.mark_crashed("OOM")
        api.set_health_ref({"sub1": h})

        resp = await client.get("/interagent/health")
        data = resp.json()
        assert data["agents"]["sub1"]["status"] == "crashed"
        assert data["agents"]["sub1"]["last_crash_error"] == "OOM"
        assert data["agents"]["sub1"]["restart_count"] == 1
