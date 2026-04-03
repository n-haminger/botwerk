"""Transport registry: centralizes bot creation for all transports.

After the removal of Telegram and Matrix transports, this module
serves as a stub that will later register WebUIBot as the sole transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from botwerk_bot.bot.protocol import BotProtocol
    from botwerk_bot.config import AgentConfig


def create_bot(config: AgentConfig, *, agent_name: str = "main") -> BotProtocol:
    """Create the transport-specific bot for *config*.

    Raises ``RuntimeError`` until a WebUI transport is registered.
    """
    factory = _TRANSPORT_FACTORIES.get("webui")
    if factory is None:
        msg = (
            "No transport registered. The WebUI transport must be registered "
            "via register_transport() before creating a bot."
        )
        raise RuntimeError(msg)
    return factory(config, agent_name=agent_name)


def register_transport(
    name: str,
    factory: object,
) -> None:
    """Register a transport factory for later use by ``create_bot``."""
    _TRANSPORT_FACTORIES[name] = factory


_TRANSPORT_FACTORIES: dict[str, object] = {}
