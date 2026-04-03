"""Tests for webhook HTTP server (FastAPI)."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from botwerk_bot.config import WebhookConfig
from botwerk_bot.webhook.manager import WebhookManager
from botwerk_bot.webhook.models import WebhookEntry, WebhookResult
from botwerk_bot.webhook.server import WebhookServer

_TOKEN = "test-secret-token"
_HOOK_TOKEN = "per-hook-secret-token"


def _make_config(**overrides: Any) -> WebhookConfig:
    defaults: dict[str, Any] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 0,
        "token": _TOKEN,
        "max_body_bytes": 262144,
        "rate_limit_per_minute": 30,
    }
    defaults.update(overrides)
    return WebhookConfig(**defaults)


def _make_hook(hook_id: str = "test-hook", **overrides: Any) -> WebhookEntry:
    defaults: dict[str, Any] = {
        "id": hook_id,
        "title": "Test Hook",
        "description": "Testing",
        "mode": "wake",
        "prompt_template": "{{msg}}",
    }
    defaults.update(overrides)
    return WebhookEntry(**defaults)


def _auth_headers(token: str = _TOKEN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _hmac_sign(body: bytes, secret: str) -> str:
    return f"sha256={hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


@pytest.fixture
async def server_client(tmp_path: Any) -> AsyncIterator[tuple[AsyncClient, AsyncMock]]:
    """Create a test client with a real WebhookServer."""
    config = _make_config()
    hooks_path = tmp_path / "webhooks.json"
    manager = WebhookManager(hooks_path=hooks_path)
    # Legacy hook with no per-hook token (uses global fallback)
    manager.add_hook(_make_hook("test-hook"))
    manager.add_hook(_make_hook("disabled-hook", enabled=False))
    # Hook with per-hook bearer token
    manager.add_hook(_make_hook("hook-with-token", token=_HOOK_TOKEN))
    # HMAC hook (GitHub-style: sha256= prefix)
    manager.add_hook(
        _make_hook(
            "hmac-hook",
            auth_mode="hmac",
            hmac_secret="hmac-test-secret",
            hmac_header="X-Hub-Signature-256",
        )
    )
    # HMAC hook (Stripe-style: sig_regex + payload_prefix)
    manager.add_hook(
        _make_hook(
            "stripe-hook",
            auth_mode="hmac",
            hmac_secret="whsec_stripe_test",
            hmac_header="Stripe-Signature",
            hmac_sig_prefix="",
            hmac_sig_regex=r"v1=([a-f0-9]+)",
            hmac_payload_prefix_regex=r"t=(\d+)",
        )
    )

    server = WebhookServer(config, manager)
    dispatch_mock = AsyncMock(
        return_value=WebhookResult(
            hook_id="test-hook",
            hook_title="Test",
            mode="wake",
            result_text="ok",
            status="success",
        )
    )
    server.set_dispatch_handler(dispatch_mock)

    transport = ASGITransport(app=server._app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, dispatch_mock


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    async def test_health_returns_ok(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth checks
# ---------------------------------------------------------------------------


class TestAuthChecks:
    async def test_no_auth_returns_401(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers={"Content-Type": "application/json"},
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 401

    async def test_wrong_token_returns_401(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers={
                "Authorization": "Bearer wrong-token",
                "Content-Type": "application/json",
            },
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Content-Type checks
# ---------------------------------------------------------------------------


class TestContentType:
    async def test_non_json_returns_415(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers={
                "Authorization": f"Bearer {_TOKEN}",
                "Content-Type": "text/plain",
            },
            content="hello",
        )
        assert resp.status_code == 415


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    async def test_invalid_json_returns_400(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers=_auth_headers(),
            content="not json{{{",
        )
        assert resp.status_code == 400

    async def test_non_object_returns_400(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers=_auth_headers(),
            content=json.dumps([1, 2, 3]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Hook routing
# ---------------------------------------------------------------------------


class TestHookRouting:
    async def test_missing_hook_returns_404(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/nonexistent",
            headers=_auth_headers(),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 404

    async def test_disabled_hook_returns_403(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/disabled-hook",
            headers=_auth_headers(),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 403

    async def test_valid_request_returns_202(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers=_auth_headers(),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert data["hook_id"] == "test-hook"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    async def test_rate_limit_returns_429(self, tmp_path: Any) -> None:
        config = _make_config(rate_limit_per_minute=2)
        hooks_path = tmp_path / "webhooks.json"
        manager = WebhookManager(hooks_path=hooks_path)
        manager.add_hook(_make_hook())

        server = WebhookServer(config, manager)
        server.set_dispatch_handler(
            AsyncMock(
                return_value=WebhookResult(
                    hook_id="test-hook",
                    hook_title="Test",
                    mode="wake",
                    result_text="ok",
                    status="success",
                )
            )
        )

        transport = ASGITransport(app=server._app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First two should pass
            for _ in range(2):
                resp = await client.post(
                    "/hooks/test-hook",
                    headers=_auth_headers(),
                    content=json.dumps({"msg": "hi"}),
                )
                assert resp.status_code == 202

            # Third should be rate limited
            resp = await client.post(
                "/hooks/test-hook",
                headers=_auth_headers(),
                content=json.dumps({"msg": "hi"}),
            )
            assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    async def test_dispatch_handler_called(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, dispatch_mock = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers=_auth_headers(),
            content=json.dumps({"msg": "hello"}),
        )
        assert resp.status_code == 202

        # Give fire-and-forget task a moment to run
        import asyncio

        await asyncio.sleep(0.1)

        dispatch_mock.assert_awaited_once_with("test-hook", {"msg": "hello"})

    async def test_no_dispatch_handler_still_202(self, tmp_path: Any) -> None:
        config = _make_config()
        hooks_path = tmp_path / "webhooks.json"
        manager = WebhookManager(hooks_path=hooks_path)
        manager.add_hook(_make_hook())

        server = WebhookServer(config, manager)
        # No dispatch handler set

        transport = ASGITransport(app=server._app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/hooks/test-hook",
                headers=_auth_headers(),
                content=json.dumps({"msg": "hi"}),
            )
            assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Per-hook token auth
# ---------------------------------------------------------------------------


class TestPerHookTokenAuth:
    async def test_per_hook_token_accepted(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/hook-with-token",
            headers=_auth_headers(_HOOK_TOKEN),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 202

    async def test_per_hook_token_rejects_global(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/hook-with-token",
            headers=_auth_headers(_TOKEN),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 401

    async def test_legacy_hook_accepts_global_token(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/test-hook",
            headers=_auth_headers(_TOKEN),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 202

    async def test_nonexistent_hook_returns_404_before_auth(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/nonexistent",
            headers={"Content-Type": "application/json"},
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# HMAC auth
# ---------------------------------------------------------------------------


class TestHmacAuth:
    async def test_hmac_valid_signature_accepted(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        body = json.dumps({"msg": "event"}).encode()
        sig = _hmac_sign(body, "hmac-test-secret")
        resp = await client.post(
            "/hooks/hmac-hook",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
            content=body,
        )
        assert resp.status_code == 202

    async def test_hmac_invalid_signature_rejected(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        body = json.dumps({"msg": "event"}).encode()
        resp = await client.post(
            "/hooks/hmac-hook",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=wrong",
            },
            content=body,
        )
        assert resp.status_code == 401

    async def test_hmac_hook_ignores_bearer(self, server_client: tuple[AsyncClient, AsyncMock]) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/hmac-hook",
            headers=_auth_headers(_TOKEN),
            content=json.dumps({"msg": "hi"}),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Stripe-style HMAC (sig_regex + payload_prefix_regex)
# ---------------------------------------------------------------------------


class TestStripeStyleHmac:
    async def test_stripe_valid_signature_accepted(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        body = json.dumps({"type": "charge.succeeded"}).encode()
        secret = "whsec_stripe_test"
        timestamp = "1614000000"
        signed_payload = f"{timestamp}.".encode() + body
        sig = hmac_mod.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        header = f"t={timestamp},v1={sig}"
        resp = await client.post(
            "/hooks/stripe-hook",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": header,
            },
            content=body,
        )
        assert resp.status_code == 202

    async def test_stripe_wrong_signature_rejected(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        body = json.dumps({"type": "charge.failed"}).encode()
        header = "t=1614000000,v1=deadbeef0000"
        resp = await client.post(
            "/hooks/stripe-hook",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": header,
            },
            content=body,
        )
        assert resp.status_code == 401

    async def test_stripe_malformed_header_rejected(
        self, server_client: tuple[AsyncClient, AsyncMock]
    ) -> None:
        client, _ = server_client
        resp = await client.post(
            "/hooks/stripe-hook",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "garbage",
            },
            content=json.dumps({"type": "test"}).encode(),
        )
        assert resp.status_code == 401
