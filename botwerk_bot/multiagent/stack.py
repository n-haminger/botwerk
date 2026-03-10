"""AgentStack: encapsulates a complete bot stack for one agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from botwerk_bot.config import AgentConfig
from botwerk_bot.workspace.init import init_workspace
from botwerk_bot.workspace.paths import BotwerkPaths, resolve_paths

if TYPE_CHECKING:
    from botwerk_bot.bot.protocol import BotProtocol

logger = logging.getLogger(__name__)


@dataclass
class AgentStack:
    """Container for one agent's entire bot stack.

    Each agent gets its own Bot → Orchestrator → CLIService pipeline,
    its own workspace, sessions, cron jobs, and webhooks.
    """

    name: str
    config: AgentConfig
    paths: BotwerkPaths
    bot: BotProtocol
    is_main: bool = False

    @classmethod
    async def create(
        cls,
        name: str,
        config: AgentConfig,
        *,
        is_main: bool = False,
    ) -> AgentStack:
        """Factory: initialize workspace and create the transport-specific bot.

        The workspace is seeded (Zone 2 + 3) and the bot created,
        but the event loop is NOT started yet — call ``run()`` for that.
        """
        import asyncio

        paths = resolve_paths(botwerk_home=config.botwerk_home)
        await asyncio.to_thread(init_workspace, paths)

        from botwerk_bot.transport_registry import create_bot

        bot = create_bot(config, agent_name=name)

        logger.info(
            "AgentStack created: name=%s home=%s main=%s transport=%s",
            name,
            paths.botwerk_home,
            is_main,
            config.transport,
        )
        return cls(name=name, config=config, paths=paths, bot=bot, is_main=is_main)

    async def run(self) -> int:
        """Start the bot (blocks until stop/crash).

        Returns exit code (0 = normal, 42 = restart requested).
        """
        return await self.bot.run()

    async def shutdown(self) -> None:
        """Gracefully shut down the bot and all observers."""
        await self.bot.shutdown()
        logger.info("AgentStack '%s' shut down", self.name)
