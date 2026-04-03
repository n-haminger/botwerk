"""Webhook HTTP server: FastAPI-based ingress for external triggers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from botwerk_bot.log_context import set_log_context
from botwerk_bot.webhook.auth import RateLimiter, validate_hook_auth

if TYPE_CHECKING:
    from botwerk_bot.config import WebhookConfig
    from botwerk_bot.webhook.manager import WebhookManager
    from botwerk_bot.webhook.models import WebhookEntry, WebhookResult

logger = logging.getLogger(__name__)

WebhookDispatchCallback = Callable[[str, dict[str, Any]], Awaitable["WebhookResult"]]


class WebhookServer:
    """HTTP server accepting webhook payloads and dispatching them.

    Routes:
    - ``GET  /health``          -- Health check for tunnel/proxy monitoring.
    - ``POST /hooks/{hook_id}`` -- Catch-all webhook endpoint.
    """

    def __init__(
        self,
        config: WebhookConfig,
        manager: WebhookManager,
    ) -> None:
        self._config = config
        self._manager = manager
        self._rate_limiter = RateLimiter(config.rate_limit_per_minute)
        self._dispatch: WebhookDispatchCallback | None = None
        self._server: uvicorn.Server | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()

        # Build FastAPI app
        self._app = FastAPI()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register all routes on the FastAPI app."""
        self._app.get("/health")(self._handle_health)
        self._app.post("/hooks/{hook_id}")(self._handle_hook)

    def set_dispatch_handler(self, handler: WebhookDispatchCallback) -> None:
        """Set the callback invoked for each valid webhook request."""
        self._dispatch = handler

    async def start(self) -> None:
        """Create the FastAPI app and start listening via Uvicorn."""
        uv_config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(uv_config)
        asyncio.ensure_future(self._server.serve())
        # Wait briefly for the server to start
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        logger.info(
            "Webhook server listening on %s:%d",
            self._config.host,
            self._config.port,
        )

    async def stop(self) -> None:
        """Shut down the server and cancel any in-flight dispatch tasks."""
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
            self._background_tasks.clear()
        if self._server:
            self._server.should_exit = True
            await asyncio.sleep(0.1)
            self._server = None
        logger.info("Webhook server stopped")

    # -- Handlers --

    async def _handle_health(self) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def _parse_body(
        self,
        request: Request,
        hook_id: str,
    ) -> tuple[dict[str, Any], bytes] | JSONResponse:
        """Parse and validate the request body. Returns (payload, raw_body) or error."""
        if not self._rate_limiter.check():
            logger.warning("Webhook rejected: rate limited hook=%s", hook_id)
            return JSONResponse({"error": "rate_limited"}, status_code=429)

        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/json"):
            logger.warning("Webhook rejected: bad content-type hook=%s", hook_id)
            return JSONResponse({"error": "content_type_must_be_json"}, status_code=415)

        raw_body = await request.body()

        try:
            payload: Any = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Webhook rejected: invalid JSON hook=%s", hook_id)
            return JSONResponse({"error": "invalid_json"}, status_code=400)

        if not isinstance(payload, dict):
            logger.warning("Webhook rejected: body not object hook=%s", hook_id)
            return JSONResponse({"error": "body_must_be_object"}, status_code=400)

        return payload, raw_body

    def _resolve_hook(
        self,
        request: Request,
        hook_id: str,
        raw_body: bytes,
    ) -> WebhookEntry | JSONResponse:
        """Look up and authenticate the hook. Returns the hook or an error response."""
        hook = self._manager.get_hook(hook_id)
        if hook is None:
            logger.warning("Webhook rejected: not found hook=%s", hook_id)
            return JSONResponse({"error": "hook_not_found"}, status_code=404)

        if not hook.enabled:
            logger.warning("Webhook rejected: disabled hook=%s", hook_id)
            return JSONResponse({"error": "hook_disabled"}, status_code=403)

        auth_header = request.headers.get("Authorization", "")
        sig_value = request.headers.get(hook.hmac_header, "") if hook.hmac_header else ""
        if not validate_hook_auth(
            hook,
            authorization=auth_header,
            signature_header_value=sig_value,
            body=raw_body,
            global_token=self._config.token,
        ):
            logger.warning("Webhook rejected: unauthorized hook=%s", hook_id)
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return hook

    async def _handle_hook(self, hook_id: str, request: Request) -> JSONResponse:
        set_log_context(operation="wh")
        logger.info("Webhook request received hook=%s method=%s", hook_id, request.method)

        body_result = await self._parse_body(request, hook_id)
        if isinstance(body_result, JSONResponse):
            return body_result

        payload, raw_body = body_result

        hook_result = self._resolve_hook(request, hook_id, raw_body)
        if isinstance(hook_result, JSONResponse):
            return hook_result

        logger.debug("Webhook validation passed hook=%s", hook_id)

        if self._dispatch:
            task = asyncio.create_task(self._safe_dispatch(hook_id, payload))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return JSONResponse({"accepted": True, "hook_id": hook_id}, status_code=202)

    async def _safe_dispatch(self, hook_id: str, payload: dict[str, Any]) -> None:
        """Run dispatch in a task with exception protection."""
        if self._dispatch is None:
            return
        try:
            await self._dispatch(hook_id, payload)
        except Exception:
            logger.exception("Webhook dispatch error for hook=%s", hook_id)
