"""Data models for multi-agent configuration."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from botwerk_bot.config import (
    AgentConfig,
    ApiConfig,
    CleanupConfig,
    CLIParametersConfig,
    HeartbeatConfig,
    StreamingConfig,
    WebhookConfig,
)


class SubAgentConfig(BaseModel):
    """Minimal sub-agent definition from agents.json.

    Only ``name`` is strictly required.
    All other fields are optional and inherit from the main agent config.
    """

    name: str

    # Group behaviour
    group_mention_only: bool | None = None

    # Optional overrides — inherit from main agent if None
    provider: str | None = None
    model: str | None = None
    log_level: str | None = None
    idle_timeout_minutes: int | None = None
    session_age_warning_hours: int | None = None
    daily_reset_hour: int | None = None
    daily_reset_enabled: bool | None = None
    max_budget_usd: float | None = None
    max_turns: int | None = None
    max_session_messages: int | None = None
    permission_mode: str | None = None
    cli_timeout: float | None = None
    reasoning_effort: str | None = None
    file_access: str | None = None
    streaming: StreamingConfig | None = None
    heartbeat: HeartbeatConfig | None = None
    cleanup: CleanupConfig | None = None
    webhooks: WebhookConfig | None = None
    api: ApiConfig | None = None
    cli_parameters: CLIParametersConfig | None = None
    user_timezone: str | None = None
    linux_user: bool | None = None  # Run CLI as dedicated Linux user (botwerk-<name>)

    # Inter-agent security
    agent_secret: str = Field(default_factory=lambda: secrets.token_hex(32))
    trust_level: Literal["privileged", "restricted"] = "restricted"
    can_contact: list[str] = Field(default_factory=list)
    accept_from: list[str] = Field(default_factory=list)


def merge_sub_agent_config(
    main: AgentConfig,
    sub: SubAgentConfig,
    agent_home: Path,
) -> AgentConfig:
    """Create a full AgentConfig by merging main config with sub-agent overrides.

    Merge: main agent defaults → ``agents.json`` explicit overrides (non-None).

    ``switch_model()`` keeps ``agents.json`` up-to-date when the user changes
    model/provider/reasoning_effort in a sub-agent chat, so no extra config
    layer is needed.
    """
    base = main.model_dump()

    # agents.json explicit overrides (non-None fields win)
    overrides = sub.model_dump(
        exclude_none=True,
        exclude={"name", "linux_user", "agent_secret", "trust_level", "can_contact", "accept_from"},
    )
    base.update(overrides)

    base["botwerk_home"] = str(agent_home)
    if sub.linux_user:
        base["linux_user"] = f"botwerk-{sub.name}"

    # Carry the agent secret through to the merged config for CLI injection.
    base["agent_secret"] = sub.agent_secret

    # Sub-agents don't need the user-facing API server (they use InterAgentBus).
    # Disable it unless the sub-agent explicitly provides an api config.
    if sub.api is None:
        base.setdefault("api", {})["enabled"] = False

    return AgentConfig(**base)
