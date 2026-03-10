"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_process_signals() -> object:
    """Globally prevent tests from sending real signals to system processes.

    Multiple modules import process_tree helpers that send real OS signals.
    Mock processes carry arbitrary PIDs (e.g. 1, 10) that correspond to real
    system processes — sending signals to them crashes the desktop session.
    """
    with (
        patch(
            "botwerk_bot.cli.process_registry.terminate_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.cli.process_registry.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.cli.executor.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.cli.gemini_provider.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.cron.execution.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.infra.pidlock.terminate_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.infra.pidlock.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "botwerk_bot.infra.pidlock.list_process_descendants",
            return_value=[],
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_real_service_management() -> object:
    """Prevent tests from stopping/starting the real systemd service.

    ``lifecycle.stop_bot()`` calls ``_stop_service_if_running()`` which runs
    ``systemctl --user stop botwerk.service`` — killing the live service on any
    machine where botwerk is installed and running.
    """
    with patch(
        "botwerk_bot.cli_commands.lifecycle._stop_service_if_running",
    ):
        yield


@pytest.fixture
def tmp_botwerk_home(tmp_path: Path) -> Path:
    """Temporary ~/.botwerk equivalent."""
    home = tmp_path / ".botwerk"
    home.mkdir()
    return home


@pytest.fixture
def tmp_workspace(tmp_botwerk_home: Path) -> Path:
    """Temporary workspace directory."""
    ws = tmp_botwerk_home / "workspace"
    ws.mkdir()
    return ws
