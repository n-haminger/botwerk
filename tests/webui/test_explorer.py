"""Tests for file explorer API routes."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from httpx import AsyncClient

from botwerk_bot.webui.auth import COOKIE_NAME, _JWT_ALGORITHM

from .conftest import TEST_SECRET


def _admin_cookie() -> dict[str, str]:
    """Create an admin JWT cookie for test requests."""
    payload = {
        "user_id": 1,
        "is_admin": True,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    return {COOKIE_NAME: token}


def _non_admin_cookie() -> dict[str, str]:
    """Create a non-admin JWT cookie for test requests."""
    payload = {
        "user_id": 2,
        "is_admin": False,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=_JWT_ALGORITHM)
    return {COOKIE_NAME: token}


def _mock_ls_output() -> bytes:
    """Simulate ls -la --time-style=+%s output."""
    return (
        b"total 12\n"
        b"drwxr-xr-x 3 user user 4096 1700000000 subdir\n"
        b"-rw-r--r-- 1 user user  100 1700000100 file.txt\n"
        b"lrwxrwxrwx 1 user user   10 1700000200 link -> target\n"
    )


@pytest.mark.asyncio
async def test_list_directory(client: AsyncClient):
    """List directory returns parsed entries."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _mock_ls_output()
    mock_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ):
        resp = await client.get(
            "/api/explorer/list",
            params={"path": "/home/user", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    # Check directory entry
    dir_entry = next(e for e in data if e["name"] == "subdir")
    assert dir_entry["type"] == "dir"
    assert dir_entry["size"] == 4096
    assert dir_entry["permissions"] == "drwxr-xr-x"

    # Check file entry
    file_entry = next(e for e in data if e["name"] == "file.txt")
    assert file_entry["type"] == "file"
    assert file_entry["size"] == 100

    # Check symlink entry
    link_entry = next(e for e in data if e["name"] == "link")
    assert link_entry["type"] == "symlink"


@pytest.mark.asyncio
async def test_list_directory_not_found(client: AsyncClient):
    """List returns 404 when directory does not exist."""
    mock_result = MagicMock()
    mock_result.returncode = 2
    mock_result.stdout = b""
    mock_result.stderr = b"No such file or directory"

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ):
        resp = await client.get(
            "/api/explorer/list",
            params={"path": "/nonexistent", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_read_file(client: AsyncClient):
    """Read file returns file content."""
    stat_result = MagicMock()
    stat_result.returncode = 0
    stat_result.stdout = b"42\n"
    stat_result.stderr = b""

    cat_result = MagicMock()
    cat_result.returncode = 0
    cat_result.stdout = b"Hello, world!"
    cat_result.stderr = b""

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return stat_result
        return cat_result

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        side_effect=side_effect,
    ):
        resp = await client.get(
            "/api/explorer/read",
            params={"path": "/home/user/file.txt", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Hello, world!"
    assert data["size"] == 42


@pytest.mark.asyncio
async def test_read_file_too_large(client: AsyncClient):
    """Read file returns 413 when file is too large."""
    stat_result = MagicMock()
    stat_result.returncode = 0
    stat_result.stdout = b"2000000\n"
    stat_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=stat_result,
    ):
        resp = await client.get(
            "/api/explorer/read",
            params={"path": "/home/user/big.bin", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_write_file(client: AsyncClient):
    """Write file calls tee with content."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b""
    mock_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ) as mock_run:
        resp = await client.put(
            "/api/explorer/write",
            json={"path": "/home/user/new.txt", "user": "testuser", "content": "new content"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # Verify sudo -u was called
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "sudo"
    assert cmd[1] == "-u"
    assert cmd[2] == "testuser"
    assert "tee" in cmd


@pytest.mark.asyncio
async def test_mkdir(client: AsyncClient):
    """Create directory calls mkdir -p."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b""
    mock_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ) as mock_run:
        resp = await client.post(
            "/api/explorer/mkdir",
            json={"path": "/home/user/newdir", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "mkdir" in cmd
    assert "-p" in cmd


@pytest.mark.asyncio
async def test_delete_path(client: AsyncClient):
    """Delete calls rm -rf."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b""
    mock_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ):
        resp = await client.request(
            "DELETE",
            "/api/explorer/delete",
            json={"path": "/home/user/old.txt", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_path_traversal_blocked(client: AsyncClient):
    """Path traversal attempts are rejected."""
    resp = await client.get(
        "/api/explorer/list",
        params={"path": "/home/user/../../etc", "user": "testuser"},
        cookies=_admin_cookie(),
    )
    assert resp.status_code == 400
    assert "traversal" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_username_blocked(client: AsyncClient):
    """Invalid usernames are rejected."""
    resp = await client.get(
        "/api/explorer/list",
        params={"path": "/home/user", "user": "test;rm -rf /"},
        cookies=_admin_cookie(),
    )
    assert resp.status_code == 400
    assert "username" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_non_admin_denied(client: AsyncClient):
    """Non-admin users are rejected."""
    resp = await client.get(
        "/api/explorer/list",
        params={"path": "/home/user", "user": "testuser"},
        cookies=_non_admin_cookie(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_download_file(client: AsyncClient):
    """Download returns binary content."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"\x89PNG\r\n\x1a\nfake image data"
    mock_result.stderr = b""

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.subprocess.run",
        return_value=mock_result,
    ):
        resp = await client.get(
            "/api/explorer/download",
            params={"path": "/home/user/image.png", "user": "testuser"},
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert "image.png" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_list_linux_users(client: AsyncClient):
    """List Linux users endpoint returns user data."""
    mock_users = [
        {"username": "testuser", "uid": 1000, "groups": ["users"], "home": "/home/testuser"},
    ]

    with patch(
        "botwerk_bot.webui.routes.explorer_routes.list_linux_users",
        return_value=mock_users,
    ):
        resp = await client.get(
            "/api/explorer/users",
            cookies=_admin_cookie(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["username"] == "testuser"
