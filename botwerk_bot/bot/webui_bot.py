"""WebUIBot: the only BotProtocol transport after Telegram/Matrix removal.

The WebUIBot does NOT run the HTTP server itself — the WebUI server is
started once in ``__main__.run_bot`` and serves all agents.  Each agent
owns its own WebUIBot instance; the bot's job is to:

1. Own the per-agent ``Orchestrator`` (so the supervisor can inject itself
   and the task hub via the startup hook).
2. Register the orchestrator with the process-wide ``ChatService``
   singleton so incoming WebSocket messages find the right orchestrator.
3. Keep the agent task alive until ``shutdown()`` is called.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from botwerk_bot.bot.protocol import BotProtocol
from botwerk_bot.notifications import NotificationService
from botwerk_bot.orchestrator.core import Orchestrator
from botwerk_bot.webui.chat_service import get_chat_service

if TYPE_CHECKING:
    from botwerk_bot.config import AgentConfig
    from botwerk_bot.multiagent.bus import AsyncInterAgentResult
    from botwerk_bot.tasks.models import TaskResult
    from botwerk_bot.workspace.paths import BotwerkPaths

logger = logging.getLogger(__name__)


class _NullNotificationService:
    """NotificationService stub for WebUI-only deployments.

    The WebUI does not broadcast messages to users outside of an open
    WebSocket.  System messages (crash reports, shared-knowledge updates)
    are logged; future work may forward them to connected sessions.
    """

    async def notify(self, chat_id: int, text: str) -> None:
        logger.info("WebUI notify chat_id=%d: %s", chat_id, text[:200])

    async def notify_all(self, text: str) -> None:
        logger.info("WebUI notify_all: %s", text[:200])


class WebUIBot(BotProtocol):
    """BotProtocol implementation backed by the WebUI chat service."""

    def __init__(self, config: AgentConfig, *, agent_name: str = "main") -> None:
        self._config = config
        self._agent_name = agent_name
        self._orchestrator: Orchestrator | None = None
        self._notifications: NotificationService = _NullNotificationService()
        self._shutdown_event = asyncio.Event()
        self._startup_hooks: list[Callable[[], Awaitable[None]]] = []
        self._abort_all_callback: Callable[[], Awaitable[int]] | None = None
        self._registered = False

    # ---- BotProtocol: properties ----------------------------------------

    @property
    def orchestrator(self) -> Orchestrator | None:
        return self._orchestrator

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def notification_service(self) -> NotificationService:
        return self._notifications

    # ---- BotProtocol: lifecycle -----------------------------------------

    async def run(self) -> int:
        """Initialize orchestrator, register with ChatService, block until shutdown."""
        self._orchestrator = await Orchestrator.create(self._config, agent_name=self._agent_name)

        # Register with the shared ChatService BEFORE user hooks run, so the
        # WebUI can route incoming messages as soon as startup finishes.
        chat_service = get_chat_service()
        chat_service.register_agent(self._agent_name, self._orchestrator)
        self._registered = True
        logger.info("WebUIBot '%s' registered with ChatService", self._agent_name)

        # Run supervisor-injected startup hooks (task hub wiring, multi-agent
        # command registration, main_ready signalling, etc.).
        for hook in list(self._startup_hooks):
            try:
                await hook()
            except Exception:
                logger.exception(
                    "WebUIBot '%s': startup hook failed", self._agent_name
                )

        # Block until shutdown() is called.
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            raise
        return 0

    async def shutdown(self) -> None:
        """Unregister from ChatService, tear down orchestrator, unblock run()."""
        if self._registered:
            try:
                get_chat_service().unregister_agent(self._agent_name)
            except Exception:
                logger.exception(
                    "WebUIBot '%s': unregister from ChatService failed", self._agent_name
                )
            self._registered = False

        if self._orchestrator is not None:
            try:
                await self._orchestrator.shutdown()
            except Exception:
                logger.exception(
                    "WebUIBot '%s': orchestrator shutdown failed", self._agent_name
                )
            self._orchestrator = None

        self._shutdown_event.set()

    # ---- BotProtocol: hooks ---------------------------------------------

    def register_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._startup_hooks.append(hook)

    def set_abort_all_callback(self, callback: Callable[[], Awaitable[int]]) -> None:
        self._abort_all_callback = callback

    # ---- BotProtocol: delivery callbacks --------------------------------

    async def on_async_interagent_result(self, result: AsyncInterAgentResult) -> None:
        logger.info(
            "WebUIBot '%s' async inter-agent result from=%s chat_id=%s",
            self._agent_name,
            getattr(result, "source_agent", "?"),
            getattr(result, "chat_id", "?"),
        )

    async def on_task_result(self, result: TaskResult) -> None:
        logger.info(
            "WebUIBot '%s' task result task_id=%s",
            self._agent_name,
            getattr(result, "task_id", "?"),
        )

    async def on_task_question(
        self,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: int,
        thread_id: int | None = None,
    ) -> None:
        logger.info(
            "WebUIBot '%s' task question task_id=%s chat_id=%d",
            self._agent_name,
            task_id,
            chat_id,
        )

    def file_roots(self, paths: BotwerkPaths) -> list[Path] | None:
        return None


def create_webui_bot(config: AgentConfig, *, agent_name: str = "main") -> WebUIBot:
    """Factory registered with ``transport_registry``."""
    return WebUIBot(config, agent_name=agent_name)
