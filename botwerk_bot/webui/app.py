"""WebUI FastAPI application: mounts API routes, health check, and SPA static serving."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from botwerk_bot.config import WebUIConfig
from botwerk_bot.webui.auth import get_current_user
from botwerk_bot.webui.routes.agent_routes import create_agent_router
from botwerk_bot.webui.routes.auth_routes import create_auth_router

logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that falls back to index.html for SPA routing.

    Any path that doesn't match a real file is served as index.html so that
    the client-side router can handle it.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except Exception:  # noqa: BLE001
            # File not found — serve index.html for SPA routing.
            scope["path"] = "/index.html"
            await super().__call__(scope, receive, send)


def create_webui_app(config: WebUIConfig) -> FastAPI:
    """Build the WebUI FastAPI application from config.

    The secret_key is auto-generated if not provided (ephemeral — tokens
    will not survive restarts unless a key is persisted in config).
    """
    secret_key = config.secret_key or secrets.token_urlsafe(32)
    if not config.secret_key:
        logger.warning(
            "WebUI secret_key not set — using ephemeral key. "
            "Run 'botwerk setup' to persist a key."
        )

    app = FastAPI(
        title="Botwerk WebUI",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # -- Proxy headers middleware ------------------------------------------

    if config.behind_proxy:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    # -- Auth dependency ---------------------------------------------------

    auth_dep = get_current_user(secret_key)

    # -- API routes (/api/) ------------------------------------------------

    api_app = FastAPI(
        title="Botwerk WebUI API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    api_app.include_router(
        create_auth_router(secret_key, auth_dep, secure_cookies=config.behind_proxy)
    )
    api_app.include_router(create_agent_router(auth_dep))

    app.mount("/api", api_app)

    # -- Health endpoint ---------------------------------------------------

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "webui"})

    # -- SPA static file serving -------------------------------------------

    frontend_dir = config.frontend_dir
    if frontend_dir:
        static_path = Path(frontend_dir)
        if static_path.is_dir():
            # Mount SPA-aware static files at /app/ — unknown paths fall back to index.html.
            app.mount(
                "/app",
                SPAStaticFiles(directory=str(static_path), html=True),
                name="frontend",
            )
            logger.info("WebUI frontend mounted from %s", static_path)
        else:
            logger.warning("WebUI frontend_dir not found: %s", frontend_dir)

    return app
