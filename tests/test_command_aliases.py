"""Tests for the centralised command alias system."""

from __future__ import annotations

import pytest

from botwerk_bot.command_aliases import resolve_alias


class TestResolveAlias:
    """Test resolve_alias() lookups."""

    @pytest.mark.parametrize(
        ("alias", "expected"),
        [
            ("i", "interrupt"),
            ("s", "status"),
            ("m", "model"),
            ("n", "new"),
        ],
    )
    def test_known_aliases(self, alias: str, expected: str) -> None:
        assert resolve_alias(alias) == expected

    def test_unknown_returns_unchanged(self) -> None:
        assert resolve_alias("status") == "status"
        assert resolve_alias("foobar") == "foobar"

    def test_empty_string(self) -> None:
        assert resolve_alias("") == ""


