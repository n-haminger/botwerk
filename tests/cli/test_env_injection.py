"""Tests for .env secret injection into subprocess environments."""

from __future__ import annotations

from pathlib import Path

from botwerk_bot.cli.base import CLIConfig
from botwerk_bot.cli.executor import _build_subprocess_env
from botwerk_bot.infra.env_secrets import clear_cache


def test_subprocess_env_merges_secrets(tmp_path: Path) -> None:
    """Secrets from .env are merged into the subprocess env dict."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET=hunter2\n")

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = _build_subprocess_env(config)

    assert env is not None
    assert env["MY_SECRET"] == "hunter2"


def test_subprocess_env_does_not_override_existing(tmp_path: Path) -> None:
    """Existing environment variables must not be overridden by .env."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("PATH=/evil\n")

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = _build_subprocess_env(config)

    assert env is not None
    assert env["PATH"] != "/evil"


def test_subprocess_env_works_without_env_file(tmp_path: Path) -> None:
    """No .env file should not break subprocess env construction."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = _build_subprocess_env(config)

    assert env is not None
    assert "BOTWERK_AGENT_NAME" in env
