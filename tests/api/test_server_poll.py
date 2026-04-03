"""Tests for HTTP polling and send fallback endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed (optional: pip install botwerk[api])")

from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from botwerk_bot.api.crypto import E2ESession
from botwerk_bot.api.server import ApiServer, _EventBuffer
from botwerk_bot.config import ApiConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_TOKEN = "test-token"
_AUTH_HEADER = {"Authorization": f"Bearer {_DEFAULT_TOKEN}"}


def _make_server(
    tmp_path: Path,
    *,
    token: str = _DEFAULT_TOKEN,
    default_chat_id: int = 42,
    message_handler: AsyncMock | None = None,
    abort_handler: AsyncMock | None = None,
) -> ApiServer:
    config = ApiConfig(
        enabled=True,
        host="127.0.0.1",
        port=0,
        token=token,
        allow_public=True,
    )
    server = ApiServer(config, default_chat_id=default_chat_id)
    server.set_message_handler(
        message_handler
        or AsyncMock(return_value=SimpleNamespace(text="ok", stream_fallback=False)),
    )
    server.set_abort_handler(abort_handler or AsyncMock(return_value=0))
    upload = tmp_path / "uploads"
    upload.mkdir()
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    server.set_file_context(allowed_roots=[tmp_path], upload_dir=upload, workspace=ws_dir)
    return server


@pytest.fixture
async def api_client(tmp_path: Path):
    """Yield (httpx AsyncClient, ApiServer)."""
    server = _make_server(tmp_path)
    transport = ASGITransport(app=server._app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, server


# ---------------------------------------------------------------------------
# _EventBuffer unit tests
# ---------------------------------------------------------------------------


class TestEventBuffer:
    def test_push_and_after(self) -> None:
        buf = _EventBuffer()
        buf.push({"type": "a"})
        buf.push({"type": "b"})
        buf.push({"type": "c"})
        assert buf.seq == 3

        events = buf.after(0)
        assert len(events) == 3
        assert events[0]["_seq"] == 1
        assert events[2]["_seq"] == 3

    def test_after_filters_by_seq(self) -> None:
        buf = _EventBuffer()
        buf.push({"type": "a"})
        buf.push({"type": "b"})
        buf.push({"type": "c"})

        events = buf.after(2)
        assert len(events) == 1
        assert events[0]["type"] == "c"
        assert events[0]["_seq"] == 3

    def test_ring_buffer_evicts_oldest(self) -> None:
        buf = _EventBuffer()
        for i in range(250):
            buf.push({"type": "evt", "i": i})

        assert buf.seq == 250
        events = buf.after(0)
        # Only last 200 should remain
        assert len(events) == 200
        assert events[0]["_seq"] == 51  # first 50 evicted

    def test_expired(self) -> None:
        import time
        from unittest.mock import patch

        buf = _EventBuffer()
        buf.push({"type": "a"})
        assert not buf.expired

        # Simulate time passing
        with patch("botwerk_bot.api.server.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 400
            assert buf.expired


# ---------------------------------------------------------------------------
# /poll endpoint tests
# ---------------------------------------------------------------------------


class TestPollEndpoint:
    async def test_no_auth_returns_401(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.get("/poll", params={"chat_id": "42", "after": "0"})
        assert resp.status_code == 401

    async def test_missing_chat_id_returns_400(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.get("/poll", headers=_AUTH_HEADER)
        assert resp.status_code == 400
        body = resp.json()
        assert "chat_id" in body["error"]

    async def test_empty_buffer_returns_empty(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.get(
            "/poll",
            params={"chat_id": "42", "after": "0"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["seq"] == 0
        assert body["events"] == []

    async def test_poll_returns_buffered_events(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, server = api_client
        # Manually push events into the buffer
        server._buffer_event(42, {"type": "text_delta", "data": "hello"})
        server._buffer_event(42, {"type": "result", "text": "world"})

        resp = await client.get(
            "/poll",
            params={"chat_id": "42", "after": "0"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["seq"] == 2
        assert len(body["events"]) == 2
        assert body["events"][0]["type"] == "text_delta"
        assert body["events"][0]["_seq"] == 1
        assert body["events"][1]["type"] == "result"

    async def test_poll_filters_by_after(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, server = api_client
        server._buffer_event(42, {"type": "a"})
        server._buffer_event(42, {"type": "b"})
        server._buffer_event(42, {"type": "c"})

        resp = await client.get(
            "/poll",
            params={"chat_id": "42", "after": "2"},
            headers=_AUTH_HEADER,
        )
        body = resp.json()
        assert len(body["events"]) == 1
        assert body["events"][0]["type"] == "c"


# ---------------------------------------------------------------------------
# /send endpoint tests
# ---------------------------------------------------------------------------


class TestSendEndpoint:
    async def test_no_auth_returns_401(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.post("/send", json={"chat_id": 42, "text": "hi"})
        assert resp.status_code == 401

    async def test_empty_message_returns_400(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.post(
            "/send",
            json={"chat_id": 42, "text": ""},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    async def test_invalid_json_returns_400(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _ = api_client
        resp = await client.post(
            "/send",
            content=b"not json",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_send_returns_202_and_dispatches(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, server = api_client

        resp = await client.post(
            "/send",
            json={"chat_id": 42, "text": "hello"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["accepted"] is True

        # Wait for background dispatch to complete
        await asyncio.sleep(0.3)

        # Result should appear in the event buffer
        buf = server._event_buffers.get(42)
        assert buf is not None
        events = buf.after(0)
        types = [e["type"] for e in events]
        assert "result" in types

    async def test_send_stop_returns_200(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, _server = api_client

        resp = await client.post(
            "/send",
            json={"chat_id": 42, "text": "/stop"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] is True
        assert body["type"] == "abort"

    async def test_send_uses_default_chat_id(
        self,
        api_client: tuple[AsyncClient, ApiServer],
    ) -> None:
        client, server = api_client

        resp = await client.post(
            "/send",
            json={"text": "hello"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 202

        await asyncio.sleep(0.3)

        # Default chat_id is 42
        buf = server._event_buffers.get(42)
        assert buf is not None

    async def test_send_handler_not_configured_returns_503(
        self,
        tmp_path: Path,
    ) -> None:
        config = ApiConfig(
            enabled=True, host="127.0.0.1", port=0,
            token=_DEFAULT_TOKEN, allow_public=True,
        )
        server = ApiServer(config, default_chat_id=42)
        # No message handler set
        transport = ASGITransport(app=server._app)
        async with AsyncClient(transport=transport, base_url="http://test") as tc:
            resp = await tc.post(
                "/send",
                json={"chat_id": 42, "text": "hello"},
                headers=_AUTH_HEADER,
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# WS + poll integration: events appear in buffer during WS streaming
# ---------------------------------------------------------------------------


class TestWsPollIntegration:
    def test_ws_events_appear_in_poll_buffer(self, tmp_path: Path) -> None:
        """Events streamed over WS are also buffered for poll retrieval."""
        from botwerk_bot.api.crypto import E2ESession

        async def fake_handler(
            _key: Any,
            _text: str,
            *,
            on_text_delta: Any,
            on_tool_activity: Any,
            on_system_status: Any,
        ) -> SimpleNamespace:
            await on_text_delta("chunk1")
            await on_text_delta("chunk2")
            return SimpleNamespace(text="chunk1chunk2", stream_fallback=False)

        server = _make_server(tmp_path, message_handler=AsyncMock(side_effect=fake_handler))
        client = TestClient(server._app)

        # Do WS handshake
        with client.websocket_connect("/ws") as ws:
            e2e = E2ESession()
            ws.send_json({
                "type": "auth",
                "token": _DEFAULT_TOKEN,
                "e2e_pk": e2e.local_pk_b64,
            })
            resp = ws.receive_json()
            assert resp["type"] == "auth_ok"
            e2e.set_remote_key(resp["e2e_pk"])

            # Send message via WS
            ws.send_text(e2e.encrypt({"type": "message", "text": "test"}))

            # Consume all WS responses
            while True:
                text = ws.receive_text()
                decrypted = e2e.decrypt(text)
                if decrypted["type"] == "result":
                    break

        # Now check the buffer directly (poll endpoint uses the same buffer)
        buf = server._event_buffers.get(42)
        assert buf is not None
        assert buf.seq > 0
        events = buf.after(0)
        types = [e["type"] for e in events]
        assert "text_delta" in types
        assert "result" in types
