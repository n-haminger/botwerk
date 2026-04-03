"""Centralised command alias resolution.

Maps short aliases to their canonical command names.  Used by the
orchestrator command registry and transport command dispatchers.
"""

from __future__ import annotations

# Alias → canonical command name (without prefix).
# Only single-word shortcuts; prefix (``/`` or ``!``) is stripped before lookup.
COMMAND_ALIASES: dict[str, str] = {
    "i": "interrupt",
    "s": "status",
    "m": "model",
    "n": "new",
}


def resolve_alias(cmd: str) -> str:
    """Return the canonical command name for *cmd*, or *cmd* unchanged."""
    return COMMAND_ALIASES.get(cmd, cmd)
