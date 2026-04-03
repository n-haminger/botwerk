"""Integration tests for E2E encrypted WebSocket protocol.

Tests the real handshake, key exchange, and encrypted message flow
using FastAPI's built-in WebSocket test support.  No mocking of
crypto primitives -- all encryption/decryption is real.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed (optional: pip install botwerk[api])")

from httpx import ASGITransport, AsyncClient
from nacl.exceptions import CryptoError
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from botwerk_bot.api.crypto import E2ESession
from botwerk_bot.api.server import ApiServer
from botwerk_bot.config import ApiConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_TOKEN = "test-token"


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


def _do_handshake_sync(
    ws: Any,
    token: str = _DEFAULT_TOKEN,
    chat_id: int | None = None,
) -> tuple[E2ESession, dict[str, Any]]:
    """Perform E2E handshake (sync, for starlette TestClient).  Returns (client_e2e, auth_ok_data)."""
    client = E2ESession()
    auth_msg: dict[str, Any] = {"type": "auth", "token": token, "e2e_pk": client.local_pk_b64}
    if chat_id is not None:
        auth_msg["chat_id"] = chat_id
    ws.send_json(auth_msg)
    resp = ws.receive_json()
    assert resp["type"] == "auth_ok"
    client.set_remote_key(resp["e2e_pk"])
    return client, resp


def _send_encrypted_sync(ws: Any, e2e: E2ESession, data: dict[str, Any]) -> None:
    ws.send_text(e2e.encrypt(data))


def _recv_encrypted_sync(ws: Any, e2e: E2ESession) -> dict[str, Any]:
    text = ws.receive_text()
    return e2e.decrypt(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_server(tmp_path: Path) -> ApiServer:
    """Return an ApiServer for WebSocket tests."""
    return _make_server(tmp_path)


# ---------------------------------------------------------------------------
# Auth + E2E handshake tests
# ---------------------------------------------------------------------------


class TestE2EHandshake:
    def test_successful_handshake(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            _e2e, resp = _do_handshake_sync(ws)
            assert resp["chat_id"] == 42
            assert "e2e_pk" in resp
            pk_bytes = base64.b64decode(resp["e2e_pk"])
            assert len(pk_bytes) == 32

    def test_auth_ok_includes_providers(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        server.set_provider_info(
            [
                {
                    "id": "claude",
                    "name": "Claude Code",
                    "color": "#F97316",
                    "models": ["haiku", "sonnet", "opus"],
                },
            ]
        )
        server.set_active_state_getter(lambda: ("sonnet", "claude"))
        client = TestClient(server._app)
        with client.websocket_connect("/ws") as ws:
            _e2e, resp = _do_handshake_sync(ws)
            assert resp["providers"] == [
                {
                    "id": "claude",
                    "name": "Claude Code",
                    "color": "#F97316",
                    "models": ["haiku", "sonnet", "opus"],
                },
            ]
            assert resp["active_provider"] == "sonnet"
            assert resp["active_model"] == "claude"

    def test_auth_ok_without_providers_has_empty_list(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            _e2e, resp = _do_handshake_sync(ws)
            assert resp["providers"] == []
            assert "active_provider" not in resp

    def test_custom_chat_id(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            _, resp = _do_handshake_sync(ws, chat_id=999)
            assert resp["chat_id"] == 999

    def test_missing_e2e_pk_rejected(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": _DEFAULT_TOKEN})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "auth_failed"
            assert "e2e_pk" in resp["message"]

    def test_invalid_e2e_pk_rejected(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {"type": "auth", "token": _DEFAULT_TOKEN, "e2e_pk": "not-valid-base64!!"},
            )
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "auth_failed"

    def test_wrong_token_rejected(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e = E2ESession()
            ws.send_json({"type": "auth", "token": "wrong", "e2e_pk": e2e.local_pk_b64})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "auth_failed"

    def test_auth_timeout(self, tmp_path: Path) -> None:
        """If client sends nothing within timeout, server closes with auth_timeout."""
        config = ApiConfig(
            enabled=True,
            host="127.0.0.1",
            port=0,
            token="tok",
            allow_public=True,
        )
        server = ApiServer(config, default_chat_id=1)
        server.set_message_handler(AsyncMock())
        server.set_abort_handler(AsyncMock(return_value=0))

        original_wait_for = asyncio.wait_for

        async def _patched_wait_for(coro: Any, *, timeout: float) -> Any:  # noqa: ASYNC109
            return await original_wait_for(coro, timeout=0.1)

        client = TestClient(server._app)
        with patch("botwerk_bot.api.server.asyncio.wait_for", side_effect=_patched_wait_for):
            with client.websocket_connect("/ws") as ws:
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert resp["code"] == "auth_timeout"


# ---------------------------------------------------------------------------
# Encrypted message flow tests
# ---------------------------------------------------------------------------


class TestEncryptedMessages:
    def test_send_message_and_receive_result(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)

            _send_encrypted_sync(ws, e2e, {"type": "message", "text": "hello"})
            result = _recv_encrypted_sync(ws, e2e)

            assert result["type"] == "result"
            assert result["text"] == "ok"
            assert result["stream_fallback"] is False

    def test_streaming_callbacks_encrypted(self, tmp_path: Path) -> None:
        """Verify text_delta, tool_activity, system_status are all encrypted."""
        events: list[dict[str, Any]] = []

        async def fake_handler(
            _chat_id: int,
            _text: str,
            *,
            on_text_delta: Any,
            on_tool_activity: Any,
            on_system_status: Any,
        ) -> SimpleNamespace:
            await on_system_status("Thinking")
            await on_tool_activity("Reading file")
            await on_text_delta("chunk1")
            await on_text_delta("chunk2")
            return SimpleNamespace(text="chunk1chunk2", stream_fallback=False)

        server = _make_server(tmp_path, message_handler=AsyncMock(side_effect=fake_handler))
        client = TestClient(server._app)

        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "message", "text": "test"})

            # Collect all events until result
            while True:
                msg = _recv_encrypted_sync(ws, e2e)
                events.append(msg)
                if msg["type"] == "result":
                    break

        types = [e["type"] for e in events]
        assert "system_status" in types
        assert "tool_activity" in types
        assert "text_delta" in types
        assert types[-1] == "result"

        deltas = [e["data"] for e in events if e["type"] == "text_delta"]
        assert deltas == ["chunk1", "chunk2"]

    def test_abort_encrypted(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "abort"})
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "abort_ok"
            assert resp["killed"] == 0

    def test_stop_command_triggers_abort(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "message", "text": "/stop"})
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "abort_ok"

    def test_empty_message_returns_encrypted_error(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "message", "text": ""})
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "error"
            assert resp["code"] == "empty"

    def test_unknown_type_returns_encrypted_error(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "unknown_cmd"})
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "error"
            assert resp["code"] == "unknown_type"

    def test_bad_ciphertext_returns_decrypt_error(self, api_server: ApiServer) -> None:
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            # Send garbage base64 that won't decrypt
            ws.send_text(base64.b64encode(b"not-real-ciphertext-at-all-" * 3).decode())
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "error"
            assert resp["code"] == "decrypt_failed"

    def test_plaintext_json_rejected_after_auth(self, api_server: ApiServer) -> None:
        """After auth, plaintext JSON should fail decryption."""
        client = TestClient(api_server._app)
        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            ws.send_text(json.dumps({"type": "message", "text": "hi"}))
            resp = _recv_encrypted_sync(ws, e2e)
            assert resp["type"] == "error"
            assert resp["code"] == "decrypt_failed"


# ---------------------------------------------------------------------------
# Cross-session isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    def test_different_sessions_different_keys(self, tmp_path: Path) -> None:
        """Two clients get independent E2E sessions with different keys."""
        server = _make_server(tmp_path)
        client = TestClient(server._app)

        with client.websocket_connect("/ws") as ws1:
            e2e1, resp1 = _do_handshake_sync(ws1, chat_id=1)

            with client.websocket_connect("/ws") as ws2:
                e2e2, resp2 = _do_handshake_sync(ws2, chat_id=2)

                # Server generates different keypairs per connection
                assert resp1["e2e_pk"] != resp2["e2e_pk"]

                # Each session works independently
                _send_encrypted_sync(ws1, e2e1, {"type": "message", "text": "from 1"})
                r1 = _recv_encrypted_sync(ws1, e2e1)
                assert r1["type"] == "result"

                _send_encrypted_sync(ws2, e2e2, {"type": "message", "text": "from 2"})
                r2 = _recv_encrypted_sync(ws2, e2e2)
                assert r2["type"] == "result"

                # Cross-session decryption must fail: client2 cannot read client1's traffic
                _send_encrypted_sync(ws1, e2e1, {"type": "abort"})
                raw_text = ws1.receive_text()
                with pytest.raises(CryptoError):
                    e2e2.decrypt(raw_text)


# ---------------------------------------------------------------------------
# File reference tests (encrypted result with file refs)
# ---------------------------------------------------------------------------


class TestEncryptedFileRefs:
    def test_file_refs_in_encrypted_result(self, tmp_path: Path) -> None:
        handler = AsyncMock(
            return_value=SimpleNamespace(
                text="Here is the file <file:/tmp/chart.png>",
                stream_fallback=False,
            ),
        )
        server = _make_server(tmp_path, message_handler=handler)
        client = TestClient(server._app)

        with client.websocket_connect("/ws") as ws:
            e2e, _ = _do_handshake_sync(ws)
            _send_encrypted_sync(ws, e2e, {"type": "message", "text": "make chart"})
            result = _recv_encrypted_sync(ws, e2e)

            assert result["type"] == "result"
            assert len(result["files"]) == 1
            assert result["files"][0]["name"] == "chart.png"
            assert result["files"][0]["is_image"] is True
