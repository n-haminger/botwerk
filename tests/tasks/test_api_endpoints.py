"""Tests for task HTTP endpoints on InternalAgentAPI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from botwerk_bot.multiagent.internal_api import InternalAgentAPI


def _make_task_hub(
    *,
    submit_returns: str = "abc123",
    list_returns: list[object] | None = None,
    question_answer: str = "Yes, use HTML",
    cancel_returns: bool = True,
) -> MagicMock:
    hub = MagicMock()
    hub.submit = MagicMock(return_value=submit_returns)
    hub.forward_question = AsyncMock(return_value=question_answer)
    hub.cancel = AsyncMock(return_value=cancel_returns)

    reg = MagicMock()
    reg.list_all.return_value = list_returns or []
    hub.registry = reg
    return hub


@pytest.fixture
async def api_client() -> AsyncClient:
    """Create test client with task-only API (no bus)."""
    api = InternalAgentAPI(bus=None, port=0)
    hub = _make_task_hub()
    api.set_task_hub(hub)
    api._app.state._test_hub = hub  # Stash for test access
    transport = ASGITransport(app=api._app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _get_hub(client: AsyncClient) -> MagicMock:
    """Retrieve stashed task hub from the app state."""
    return client._transport.app.state._test_hub  # type: ignore[union-attr]


class TestTaskCreate:
    async def test_creates_task(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/tasks/create",
            json={"from": "main", "prompt": "build website", "name": "Website"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "abc123"

    async def test_missing_prompt(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/tasks/create", json={"from": "main"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    async def test_invalid_json(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/tasks/create",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


class TestTaskAskParent:
    async def test_returns_answer(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/tasks/ask_parent",
            json={"task_id": "abc", "question": "Which framework?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["answer"] == "Yes, use HTML"

    async def test_missing_fields(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/tasks/ask_parent", json={"task_id": "abc"})
        assert resp.status_code == 400


class TestTaskList:
    async def test_returns_empty(self, api_client: AsyncClient) -> None:
        resp = await api_client.get("/tasks/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tasks"] == []


class TestTaskCancel:
    async def test_cancels_task(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/tasks/cancel", json={"task_id": "abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_missing_task_id(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/tasks/cancel", json={})
        assert resp.status_code == 400


class TestTaskDelete:
    async def test_deletes_finished_task(self, api_client: AsyncClient) -> None:
        hub = _get_hub(api_client)
        entry = MagicMock()
        entry.parent_agent = "main"
        entry.status = "done"
        hub.registry.get.return_value = entry
        hub.registry.delete.return_value = True

        resp = await api_client.post(
            "/tasks/delete",
            json={"task_id": "abc", "from": "main"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_rejects_running_task(self, api_client: AsyncClient) -> None:
        hub = _get_hub(api_client)
        entry = MagicMock()
        entry.parent_agent = "main"
        entry.status = "running"
        hub.registry.get.return_value = entry
        hub.registry.delete.return_value = False

        resp = await api_client.post(
            "/tasks/delete",
            json={"task_id": "abc", "from": "main"},
        )
        assert resp.status_code == 409

    async def test_not_found(self, api_client: AsyncClient) -> None:
        hub = _get_hub(api_client)
        hub.registry.get.return_value = None

        resp = await api_client.post("/tasks/delete", json={"task_id": "nope"})
        assert resp.status_code == 404

    async def test_unauthorized(self, api_client: AsyncClient) -> None:
        hub = _get_hub(api_client)
        entry = MagicMock()
        entry.parent_agent = "main"
        hub.registry.get.return_value = entry

        resp = await api_client.post(
            "/tasks/delete",
            json={"task_id": "abc", "from": "other_agent"},
        )
        assert resp.status_code == 403

    async def test_missing_task_id(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/tasks/delete", json={})
        assert resp.status_code == 400


class TestTaskOnlyMode:
    async def test_no_interagent_routes_without_bus(self, api_client: AsyncClient) -> None:
        """When bus is None, interagent routes should not exist."""
        resp = await api_client.post(
            "/interagent/send",
            json={"from": "a", "to": "b", "message": "hi"},
        )
        assert resp.status_code == 404 or resp.status_code == 405

    async def test_task_routes_work_without_bus(self, api_client: AsyncClient) -> None:
        resp = await api_client.get("/tasks/list")
        assert resp.status_code == 200
