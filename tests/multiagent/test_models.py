"""Tests for multiagent/models.py: SubAgentConfig and merge_sub_agent_config."""

from __future__ import annotations

from pathlib import Path

from botwerk_bot.config import AgentConfig, ApiConfig
from botwerk_bot.multiagent.models import SubAgentConfig, merge_sub_agent_config


class TestSubAgentConfig:
    """Test SubAgentConfig model validation and defaults."""

    def test_minimal_config(self) -> None:
        cfg = SubAgentConfig(name="sub1")
        assert cfg.name == "sub1"
        assert cfg.provider is None
        assert cfg.model is None

    def test_with_overrides(self) -> None:
        cfg = SubAgentConfig(
            name="sub1",
            provider="codex",
            model="gpt-4",
        )
        assert cfg.provider == "codex"
        assert cfg.model == "gpt-4"

    def test_model_dump_excludes_none(self) -> None:
        cfg = SubAgentConfig(name="sub1")
        dumped = cfg.model_dump(exclude_none=True)
        assert "provider" not in dumped
        assert "model" not in dumped


class TestMergeSubAgentConfig:
    """Test merge_sub_agent_config behavior."""

    def _main_config(self) -> AgentConfig:
        return AgentConfig(
            provider="claude",
            model="opus",
            botwerk_home="/main/home",
            cli_timeout=600,
        )

    def test_inherits_from_main(self) -> None:
        """Sub-agent inherits main config values when not overridden."""
        main = self._main_config()
        sub = SubAgentConfig(name="sub1")
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.provider == "claude"
        assert result.model == "opus"
        assert result.cli_timeout == 600

    def test_overrides_from_sub(self) -> None:
        """Sub-agent overrides take precedence over main config."""
        main = self._main_config()
        sub = SubAgentConfig(
            name="sub1",
            provider="codex",
            model="gpt-4",
            cli_timeout=300,
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.provider == "codex"
        assert result.model == "gpt-4"
        assert result.cli_timeout == 300

    def test_botwerk_home_always_set_to_agent_home(self) -> None:
        """botwerk_home is always the agent's home dir, not main's."""
        main = self._main_config()
        sub = SubAgentConfig(name="sub1")
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.botwerk_home == "/agents/sub1"

    def test_partial_overrides(self) -> None:
        """Only specified fields override, rest inherit from main."""
        main = self._main_config()
        sub = SubAgentConfig(
            name="sub1",
            model="sonnet",
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.model == "sonnet"
        assert result.provider == "claude"  # inherited

    def test_api_disabled_when_not_overridden(self) -> None:
        """Sub-agent without explicit api config gets api.enabled=False."""
        main = self._main_config()
        main.api = ApiConfig(enabled=True, port=8741)
        sub = SubAgentConfig(name="sub1")
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.api.enabled is False
        assert result.api.port == 8741  # rest inherited

    def test_api_preserved_when_explicitly_overridden(self) -> None:
        """Sub-agent with explicit api config keeps their settings."""
        main = self._main_config()
        main.api = ApiConfig(enabled=True, port=8741)
        sub = SubAgentConfig(
            name="sub1",
            api=ApiConfig(enabled=True, port=8742),
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))

        assert result.api.enabled is True
        assert result.api.port == 8742

    def test_linux_user_derived_from_name(self) -> None:
        """linux_user=True in SubAgentConfig becomes 'botwerk-<name>' in AgentConfig."""
        main = self._main_config()
        sub = SubAgentConfig(
            name="codex",
            linux_user=True,
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/codex"))
        assert result.linux_user == "botwerk-codex"

    def test_linux_user_not_set_by_default(self) -> None:
        """linux_user is empty by default."""
        main = self._main_config()
        sub = SubAgentConfig(name="sub1")
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))
        assert result.linux_user == ""

    def test_linux_user_false_not_set(self) -> None:
        """linux_user=False keeps the field empty."""
        main = self._main_config()
        sub = SubAgentConfig(
            name="sub1",
            linux_user=False,
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/sub1"))
        assert result.linux_user == ""
