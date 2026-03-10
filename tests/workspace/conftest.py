"""Fixtures for workspace tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from botwerk_bot.cli.auth import AuthResult, AuthStatus


@pytest.fixture(autouse=True)
def _mock_cli_auth():
    """Mock CLI auth so RulesSelector doesn't delete CLAUDE.md test files.

    Without this, RulesSelector._cleanup_stale_files() removes all CLAUDE.md
    files when no CLIs are authenticated (e.g., in CI).
    """
    mock_results = {
        "claude": AuthResult("claude", AuthStatus.AUTHENTICATED),
        "codex": AuthResult("codex", AuthStatus.AUTHENTICATED),
        "gemini": AuthResult("gemini", AuthStatus.NOT_FOUND),
    }
    with patch("botwerk_bot.cli.auth.check_all_auth", return_value=mock_results):
        yield
