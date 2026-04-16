"""Chat service: decouples WebSocket layer from orchestrator internals."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from botwerk_bot.session import SessionKey

logger = logging.getLogger(__name__)

_TextCallback = Callable[[str], Awaitable[None]]
_SystemStatusCallback = Callable[[str | None], Awaitable[None]]


@dataclass
class ChatResult:
    """Result of a chat message processed by the orchestrator."""

    text: str
    error: bool = False


class ChatService:
    """Wraps orchestrator access for the WebUI WebSocket layer.

    Each registered agent maps to an Orchestrator instance.  The service
    provides a transport-agnostic interface for sending messages and
    aborting in-flight requests.
    """

    def __init__(self) -> None:
        self._orchestrators: dict[str, Any] = {}

    def register_agent(self, name: str, orchestrator: Any) -> None:
        """Register an orchestrator instance for *name*."""
        self._orchestrators[name] = orchestrator
        logger.info("ChatService: registered agent %r", name)

    def unregister_agent(self, name: str) -> None:
        """Remove a previously registered agent."""
        self._orchestrators.pop(name, None)

    def has_agent(self, name: str) -> bool:
        """Return True if *name* has a registered orchestrator."""
        return name in self._orchestrators

    @property
    def agent_names(self) -> list[str]:
        """Return the list of registered agent names."""
        return list(self._orchestrators)

    async def handle_message(
        self,
        agent_name: str,
        session_key: SessionKey,
        text: str,
        *,
        on_text_delta: _TextCallback | None = None,
        on_tool_activity: _TextCallback | None = None,
        on_system_status: _SystemStatusCallback | None = None,
    ) -> ChatResult:
        """Send *text* to the agent's orchestrator with streaming callbacks.

        Returns a ``ChatResult`` with the final response text.
        """
        orch = self._orchestrators.get(agent_name)
        if orch is None:
            return ChatResult(text=f"Agent '{agent_name}' is not available.", error=True)

        try:
            result = await orch.handle_message_streaming(
                session_key,
                text,
                on_text_delta=on_text_delta,
                on_tool_activity=on_tool_activity,
                on_system_status=on_system_status,
            )
            return ChatResult(text=result.text)
        except Exception:
            logger.exception("ChatService: error handling message for agent %r", agent_name)
            return ChatResult(text="An internal error occurred.", error=True)

    async def abort(self, agent_name: str, chat_id: int) -> bool:
        """Abort the in-flight request for *agent_name* / *chat_id*.

        Returns True if an abort signal was sent, False if the agent has
        no registered orchestrator or no process registry.
        """
        orch = self._orchestrators.get(agent_name)
        if orch is None:
            return False
        try:
            registry = getattr(orch, "_process_registry", None)
            if registry is not None:
                registry.abort(chat_id)
                return True
        except Exception:
            logger.exception("ChatService: error aborting for agent %r", agent_name)
        return False


# Process-wide ChatService singleton.  The WebUI server and every WebUIBot
# instance resolve the same object via ``get_chat_service()``.  This is the
# bridge between the supervisor (which owns the orchestrators) and the
# WebUI WebSocket layer (which speaks to the browser).
_CHAT_SERVICE_SINGLETON: ChatService | None = None


def get_chat_service() -> ChatService:
    """Return the process-wide ChatService (creating it on first access)."""
    global _CHAT_SERVICE_SINGLETON  # noqa: PLW0603
    if _CHAT_SERVICE_SINGLETON is None:
        _CHAT_SERVICE_SINGLETON = ChatService()
    return _CHAT_SERVICE_SINGLETON


def reset_chat_service() -> None:
    """Reset the singleton (test-only)."""
    global _CHAT_SERVICE_SINGLETON  # noqa: PLW0603
    _CHAT_SERVICE_SINGLETON = None
