"""Transport registry: centralizes bot creation for all transports.

After the removal of Telegram and Matrix transports the WebUI is the
only transport.  The registry still exists so tests and embedders can
swap in a fake transport when needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from botwerk_bot.bot.protocol import BotProtocol
    from botwerk_bot.config import AgentConfig


_BotFactory = Callable[..., "BotProtocol"]


def create_bot(config: AgentConfig, *, agent_name: str = "main") -> BotProtocol:
    """Create the transport-specific bot for *config*."""
    factory = _TRANSPORT_FACTORIES.get("webui")
    if factory is None:
        # Lazy default registration so the WebUIBot import does not run at
        # module load time (tests may override before any bot is created).
        from botwerk_bot.bot.webui_bot import create_webui_bot

        factory = create_webui_bot
        _TRANSPORT_FACTORIES["webui"] = factory
    return factory(config, agent_name=agent_name)


def register_transport(name: str, factory: _BotFactory) -> None:
    """Register a transport factory for later use by ``create_bot``."""
    _TRANSPORT_FACTORIES[name] = factory


def clear_transports() -> None:
    """Remove all registered transports (test-only)."""
    _TRANSPORT_FACTORIES.clear()


_TRANSPORT_FACTORIES: dict[str, _BotFactory] = {}
