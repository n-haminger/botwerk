"""Package version checking against GitHub Releases."""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_GITHUB_RELEASES_URL = "https://api.github.com/repos/n-haminger/botwerk/releases"
_PACKAGE_NAME = "botwerk"
_TIMEOUT = 10.0


def get_current_version() -> str:
    """Return the installed version of botwerk."""
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse dotted version string into a comparable tuple."""
    parts: list[int] = []
    for segment in v.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """Result of a GitHub Releases version check."""

    current: str
    latest: str
    update_available: bool
    summary: str


async def check_github_releases() -> VersionInfo | None:
    """Check GitHub Releases for the latest version. Returns None on failure."""
    current = get_current_version()
    headers = {"Accept": "application/vnd.github+json"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            resp = await client.get(f"{_GITHUB_RELEASES_URL}/latest")
            if resp.status_code != 200:
                return None
            data = resp.json()
    except (httpx.HTTPError, TimeoutError, ValueError):
        logger.debug("GitHub Releases version check failed", exc_info=True)
        return None

    tag: str = data.get("tag_name", "")
    if not tag:
        return None

    latest = tag.lstrip("v")
    summary: str = data.get("name", "") or ""
    update_available = _parse_version(latest) > _parse_version(current)
    return VersionInfo(
        current=current,
        latest=latest,
        update_available=update_available,
        summary=summary,
    )


async def fetch_changelog(version: str) -> str | None:
    """Fetch release notes for *version* from GitHub Releases.

    Tries ``v{version}`` tag first, then ``{version}`` without prefix.
    Returns the release body (Markdown) or ``None`` on failure.
    """
    headers = {"Accept": "application/vnd.github+json"}
    for tag in (f"v{version}", version):
        url = f"{_GITHUB_RELEASES_URL}/tags/{tag}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                body: str = data.get("body", "")
                if body:
                    return body.strip()
        except (httpx.HTTPError, TimeoutError, ValueError):
            logger.debug("GitHub release fetch failed for tag %s", tag, exc_info=True)
    return None
