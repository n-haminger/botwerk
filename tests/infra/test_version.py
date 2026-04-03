"""Tests for GitHub Releases version checking."""

from __future__ import annotations

import importlib.metadata
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from botwerk_bot.infra.version import (
    VersionInfo,
    _parse_version,
    check_github_releases,
    fetch_changelog,
    get_current_version,
)


class TestParseVersion:
    """Test dotted version string parsing."""

    def test_standard_triple(self) -> None:
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_single_digit(self) -> None:
        assert _parse_version("5") == (5,)

    def test_four_segments(self) -> None:
        assert _parse_version("1.0.0.1") == (1, 0, 0, 1)

    def test_non_numeric_suffix_stops(self) -> None:
        assert _parse_version("1.2.3a1") == (1, 2)

    def test_empty_string(self) -> None:
        assert _parse_version("") == ()

    def test_comparison_newer(self) -> None:
        assert _parse_version("2.0.0") > _parse_version("1.9.9")

    def test_comparison_equal(self) -> None:
        assert _parse_version("1.0.0") == _parse_version("1.0.0")

    def test_comparison_older(self) -> None:
        assert _parse_version("0.1.0") < _parse_version("0.2.0")

    def test_comparison_minor_bump(self) -> None:
        assert _parse_version("1.1.0") > _parse_version("1.0.99")


class TestGetCurrentVersion:
    """Test installed version detection."""

    def test_returns_installed_version(self) -> None:
        with patch("botwerk_bot.infra.version.importlib.metadata.version", return_value="1.5.0"):
            assert get_current_version() == "1.5.0"

    def test_returns_fallback_when_not_installed(self) -> None:
        with patch(
            "botwerk_bot.infra.version.importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            assert get_current_version() == "0.0.0"


def _mock_httpx_client(
    *, status: int = 200, json_data: dict | None = None, error: Exception | None = None
) -> MagicMock:
    """Build a mock httpx.AsyncClient for GitHub API tests."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data or {})

    mock_client = MagicMock()

    if error:
        mock_client.get = AsyncMock(side_effect=error)
    else:
        mock_client.get = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def mock_client_cm(**_kwargs: object) -> AsyncGenerator[MagicMock, None]:
        yield mock_client

    return mock_client_cm


class TestCheckGithubReleases:
    """Test GitHub Releases API response handling."""

    async def test_returns_version_info_when_update_available(self) -> None:
        mock = _mock_httpx_client(json_data={"tag_name": "v2.0.0", "name": "Release 2.0.0"})

        with (
            patch("botwerk_bot.infra.version.get_current_version", return_value="1.0.0"),
            patch("botwerk_bot.infra.version.httpx.AsyncClient", mock),
        ):
            result = await check_github_releases()

        assert result is not None
        assert result.current == "1.0.0"
        assert result.latest == "2.0.0"
        assert result.update_available is True
        assert result.summary == "Release 2.0.0"

    async def test_no_update_when_same_version(self) -> None:
        mock = _mock_httpx_client(json_data={"tag_name": "v1.0.0", "name": "Current"})

        with (
            patch("botwerk_bot.infra.version.get_current_version", return_value="1.0.0"),
            patch("botwerk_bot.infra.version.httpx.AsyncClient", mock),
        ):
            result = await check_github_releases()

        assert result is not None
        assert result.update_available is False

    async def test_returns_none_on_http_error(self) -> None:
        mock = _mock_httpx_client(status=500)

        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await check_github_releases()

        assert result is None

    async def test_returns_none_on_network_error(self) -> None:
        mock = _mock_httpx_client(error=httpx.HTTPError("connection failed"))

        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await check_github_releases()

        assert result is None

    async def test_returns_none_on_missing_tag(self) -> None:
        mock = _mock_httpx_client(json_data={})

        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await check_github_releases()

        assert result is None

    async def test_strips_v_prefix_from_tag(self) -> None:
        mock = _mock_httpx_client(json_data={"tag_name": "v3.1.0", "name": ""})

        with (
            patch("botwerk_bot.infra.version.get_current_version", return_value="1.0.0"),
            patch("botwerk_bot.infra.version.httpx.AsyncClient", mock),
        ):
            result = await check_github_releases()

        assert result is not None
        assert result.latest == "3.1.0"

    def test_version_info_is_frozen(self) -> None:
        info = VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="test")
        assert info.current == "1.0.0"
        assert info.update_available is True


class TestFetchChangelog:
    """Test GitHub Releases changelog fetching."""

    async def test_returns_body_for_v_prefixed_tag(self) -> None:
        mock = _mock_httpx_client(json_data={"body": "## What's new\n\n- Feature A"})
        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await fetch_changelog("1.0.0")
        assert result is not None
        assert "Feature A" in result

    async def test_returns_none_on_404(self) -> None:
        mock = _mock_httpx_client(status=404)
        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await fetch_changelog("99.0.0")
        assert result is None

    async def test_returns_none_on_network_error(self) -> None:
        mock = _mock_httpx_client(error=httpx.HTTPError("connection failed"))
        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await fetch_changelog("1.0.0")
        assert result is None

    async def test_returns_none_on_empty_body(self) -> None:
        mock = _mock_httpx_client(json_data={"body": ""})
        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await fetch_changelog("1.0.0")
        assert result is None

    async def test_strips_whitespace(self) -> None:
        mock = _mock_httpx_client(json_data={"body": "  changelog text  \n\n"})
        with patch("botwerk_bot.infra.version.httpx.AsyncClient", mock):
            result = await fetch_changelog("1.0.0")
        assert result == "changelog text"
