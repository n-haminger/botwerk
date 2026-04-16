"""WebUI startup: integration point between botwerk core and the WebUI server."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from botwerk_bot.webui.app import create_webui_app
from botwerk_bot.webui.chat_service import get_chat_service
from botwerk_bot.webui.database import init_db

if TYPE_CHECKING:
    from botwerk_bot.config import AgentConfig

logger = logging.getLogger(__name__)


async def start_webui(config: AgentConfig) -> FastAPI:
    """Initialize and start the WebUI server.

    1. Initializes the database.
    2. Creates the FastAPI app.
    3. Wires up the ChatService with agent orchestrators.
    4. Starts Uvicorn in the asyncio event loop.
    5. Returns the app instance for testing.

    Args:
        config: The main AgentConfig with webui settings.

    Returns:
        The configured FastAPI application.
    """
    botwerk_home = Path(config.botwerk_home).expanduser()
    db_path = str(botwerk_home / "webui.db")
    upload_dir = botwerk_home / "webui_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize the database
    engine = await init_db(db_path)

    # 2. Create the FastAPI app (uses the process-wide ChatService that
    #    WebUIBot instances register themselves with).
    chat_service = get_chat_service()
    app = create_webui_app(
        config=config.webui,
        chat_service=chat_service,
        upload_dir=upload_dir,
    )

    # Store session factory on app.state for WebSocket handler
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.session_factory = session_factory

    # 3. Start Uvicorn as an asyncio server (non-blocking)
    uvi_config = uvicorn.Config(
        app=app,
        host=config.webui.host,
        port=config.webui.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uvi_config)

    # Store server reference for clean shutdown
    app.state.uvicorn_server = server

    logger.info(
        "Starting WebUI on %s:%d",
        config.webui.host,
        config.webui.port,
    )

    # Start the server as a background task so it doesn't block the event loop
    asyncio.create_task(server.serve())

    return app
