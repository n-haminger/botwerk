"""Command registry and OrchestratorResult."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from botwerk_bot.command_aliases import resolve_alias
from botwerk_bot.orchestrator.selectors.models import ButtonGrid

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from botwerk_bot.orchestrator.core import Orchestrator
    from botwerk_bot.session.key import SessionKey

CommandHandler = Callable[
    ["Orchestrator", "SessionKey", str], Awaitable["OrchestratorResult | None"]
]


class OrchestratorResult(BaseModel):
    """Structured return from handle_message."""

    text: str
    stream_fallback: bool = False
    buttons: ButtonGrid | None = None


@dataclass(frozen=True, slots=True)
class _CommandEntry:
    name: str
    handler: CommandHandler
    match_prefix: bool


class CommandRegistry:
    """Registry of slash commands with async dispatch."""

    def __init__(self) -> None:
        self._commands: list[_CommandEntry] = []

    def register_async(self, name: str, handler: CommandHandler) -> None:
        self._commands.append(
            _CommandEntry(name=name, handler=handler, match_prefix=name.endswith(" "))
        )

    async def dispatch(
        self,
        cmd: str,
        orch: Orchestrator,
        key: SessionKey,
        text: str,
    ) -> OrchestratorResult | None:
        """Dispatch *cmd* to a registered handler. Returns None if unknown.

        Strips ``@botname`` suffixes so group commands like
        ``/status@mybot`` match the registered ``/status`` entry.
        """
        # Normalize: "/status@mybot args" -> "/status args"
        parts = cmd.split(None, 1)
        if parts and "@" in parts[0]:
            parts[0] = parts[0].split("@", 1)[0]
            cmd = " ".join(parts)

        # Resolve aliases: "/s" -> "/status", "/n" -> "/new", etc.
        cmd_parts = cmd.split(None, 1)
        if cmd_parts and cmd_parts[0].startswith("/"):
            bare = cmd_parts[0][1:]
            canonical = resolve_alias(bare)
            if canonical != bare:
                cmd_parts[0] = f"/{canonical}"
                cmd = " ".join(cmd_parts)

        for entry in self._commands:
            if entry.match_prefix:
                if cmd.startswith(entry.name):
                    logger.debug("Command matched cmd=%s", entry.name)
                    return await entry.handler(orch, key, text)
            elif cmd == entry.name:
                logger.debug("Command matched cmd=%s", entry.name)
                return await entry.handler(orch, key, text)
        return None
