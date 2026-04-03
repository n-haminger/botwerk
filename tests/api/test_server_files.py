"""Tests for API server file download and upload endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed (optional: pip install botwerk[api])")

from httpx import ASGITransport, AsyncClient

from botwerk_bot.api.server import ApiServer, _parse_file_refs
from botwerk_bot.config import ApiConfig

# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestParseFileRefs:
    def test_no_files(self) -> None:
        assert _parse_file_refs("just text") == []

    def test_single_file(self) -> None:
        refs = _parse_file_refs("result <file:/tmp/output.txt>")
        assert len(refs) == 1
        assert refs[0]["path"] == "/tmp/output.txt"
        assert refs[0]["name"] == "output.txt"
        assert refs[0]["is_image"] is False

    def test_image_file(self) -> None:
        refs = _parse_file_refs("<file:/tmp/photo.jpg>")
        assert refs[0]["is_image"] is True

    def test_multiple_files(self) -> None:
        refs = _parse_file_refs("<file:/a.txt> and <file:/b.png>")
        assert len(refs) == 2
        assert refs[0]["is_image"] is False
        assert refs[1]["is_image"] is True

    def test_windows_file_ref_is_normalized(self) -> None:
        with patch("botwerk_bot.files.tags.is_windows", return_value=True):
            refs = _parse_file_refs("<file:/C/Users/alice/output_to_user/out.zip>")
        assert refs[0]["path"] == "C:/Users/alice/output_to_user/out.zip"
        assert refs[0]["name"] == "out.zip"


# ---------------------------------------------------------------------------
# Integration tests for HTTP endpoints
# ---------------------------------------------------------------------------


def _make_server(tmp_path: Path) -> ApiServer:
    """Build an ApiServer with file handlers for testing."""
    config = ApiConfig(
        enabled=True,
        host="127.0.0.1",
        port=0,
        token="test-token",
        allow_public=True,
    )
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    server = ApiServer(config, default_chat_id=1)
    server.set_message_handler(AsyncMock())
    server.set_abort_handler(AsyncMock(return_value=0))
    server.set_file_context(
        allowed_roots=[tmp_path],
        upload_dir=upload_dir,
        workspace=workspace,
    )

    return server


@pytest.fixture
async def api_client(tmp_path: Path):
    """Create an httpx async client with the API server app."""
    server = _make_server(tmp_path)
    transport = ASGITransport(app=server._app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._tmp_path = tmp_path  # type: ignore[attr-defined]
        client._server = server  # type: ignore[attr-defined]
        yield client


class TestFileDownload:
    async def test_no_auth_returns_401(self, api_client: AsyncClient) -> None:
        resp = await api_client.get("/files", params={"path": "/tmp/test"})
        assert resp.status_code == 401

    async def test_wrong_token_returns_401(self, api_client: AsyncClient) -> None:
        resp = await api_client.get(
            "/files",
            params={"path": "/tmp/test"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    async def test_missing_path_returns_400(self, api_client: AsyncClient) -> None:
        resp = await api_client.get(
            "/files",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400

    async def test_nonexistent_file_returns_404(self, api_client: AsyncClient) -> None:
        tmp = api_client._tmp_path  # type: ignore[attr-defined]
        resp = await api_client.get(
            "/files",
            params={"path": str(tmp / "nonexistent.txt")},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 404

    async def test_valid_file_download(self, api_client: AsyncClient) -> None:
        tmp = api_client._tmp_path  # type: ignore[attr-defined]
        test_file = tmp / "download_test.txt"
        test_file.write_text("hello world")

        resp = await api_client.get(
            "/files",
            params={"path": str(test_file)},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        assert resp.content == b"hello world"

    async def test_path_outside_allowed_roots_returns_403(self, api_client: AsyncClient) -> None:
        resp = await api_client.get(
            "/files",
            params={"path": "/etc/hostname"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 403


class TestFileUpload:
    async def test_no_auth_returns_401(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/upload")
        assert resp.status_code == 401

    async def test_upload_file(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload",
            files={"file": ("test.txt", b"test content", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "test.txt"
        assert body["size"] == 12
        assert "prompt" in body
        assert "[INCOMING FILE]" in body["prompt"]
        assert "via API" in body["prompt"]

    async def test_upload_with_caption(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload",
            files={"file": ("photo.jpg", b"img data", "image/jpeg")},
            data={"caption": "Look at this photo"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Look at this photo" in body["prompt"]

    def test_uploaded_file_exists_on_disk(self, tmp_path: Path) -> None:
        """Verify prepare_destination creates the file in the right place."""
        from botwerk_bot.files.storage import prepare_destination

        dest = prepare_destination(tmp_path, "data.csv")
        dest.write_bytes(b"saved content")
        assert dest.is_file()
        assert dest.read_bytes() == b"saved content"


class TestMultiFileUpload:
    async def test_no_auth_returns_401(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/upload/multi")
        assert resp.status_code == 401

    async def test_upload_multiple_files(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload/multi",
            files=[
                ("file", ("first.txt", b"content one", "text/plain")),
                ("file", ("second.txt", b"content two", "text/plain")),
            ],
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 2
        assert body["files"][0]["name"] == "first.txt"
        assert body["files"][0]["size"] == 11
        assert body["files"][1]["name"] == "second.txt"
        assert body["files"][1]["size"] == 11
        assert body["total_size"] == 22
        assert "[INCOMING FILE]" in body["prompt"]

    async def test_upload_with_caption(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload/multi",
            files=[
                ("file", ("a.jpg", b"img1", "image/jpeg")),
                ("file", ("b.png", b"img2", "image/png")),
            ],
            data={"caption": "Check these images"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 2
        assert "Check these images" in body["prompt"]

    async def test_no_files_returns_400(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload/multi",
            content=b"not multipart",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400

    async def test_single_file_works(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload/multi",
            files=[("file", ("only.txt", b"solo", "text/plain"))],
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 1
        assert body["files"][0]["name"] == "only.txt"

    async def test_files_exist_on_disk(self, api_client: AsyncClient) -> None:
        resp = await api_client.post(
            "/upload/multi",
            files=[
                ("file", ("x.txt", b"aaa", "text/plain")),
                ("file", ("y.txt", b"bbb", "text/plain")),
            ],
            headers={"Authorization": "Bearer test-token"},
        )
        body = resp.json()
        for entry in body["files"]:
            assert Path(entry["path"]).is_file()

    async def test_cumulative_size_limit_returns_413(self, api_client: AsyncClient) -> None:
        """Exceeding the cumulative upload limit returns 413 and cleans up files."""
        server = api_client._server  # type: ignore[attr-defined]
        original = server._max_upload_bytes
        server._max_upload_bytes = 100  # tiny limit for testing
        try:
            resp = await api_client.post(
                "/upload/multi",
                files=[
                    ("file", ("a.bin", b"A" * 60, "application/octet-stream")),
                    ("file", ("b.bin", b"B" * 60, "application/octet-stream")),
                ],
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status_code == 413
            body = resp.json()
            assert "limit" in body["error"]
        finally:
            server._max_upload_bytes = original
