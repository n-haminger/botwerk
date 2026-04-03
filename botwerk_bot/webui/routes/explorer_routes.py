"""File explorer API routes — all operations execute as the selected Linux user."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from botwerk_bot.webui.linux_users import list_linux_users
from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)

# Maximum file size for text read (1 MB)
_MAX_READ_SIZE = 1_048_576
# Maximum file size for write (1 MB)
_MAX_WRITE_SIZE = 1_048_576


class FileEntry(BaseModel):
    """A single directory entry."""

    name: str
    type: str  # "file", "dir", "symlink"
    size: int
    permissions: str
    modified_at: float


class WriteRequest(BaseModel):
    """Request body for writing a file."""

    path: str
    user: str
    content: str = Field(max_length=_MAX_WRITE_SIZE)


class MkdirRequest(BaseModel):
    """Request body for creating a directory."""

    path: str
    user: str


class DeleteRequest(BaseModel):
    """Request body for deleting a file or directory."""

    path: str
    user: str


def _validate_path(path: str) -> str:
    """Validate and normalize a path to prevent traversal attacks.

    Returns the resolved absolute path string.
    Raises HTTPException on invalid paths.
    """
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")

    # Check for path traversal patterns in raw input before normalization
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    # Normalize the path
    normalized = os.path.normpath(path)

    # Must be absolute
    if not os.path.isabs(normalized):
        raise HTTPException(status_code=400, detail="Path must be absolute")

    return normalized


def _validate_username(user: str) -> str:
    """Validate username to prevent command injection."""
    import re

    if not user or not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", user) or len(user) > 64:
        raise HTTPException(status_code=400, detail="Invalid username")
    return user


def _sudo_run(
    user: str,
    cmd: list[str],
    *,
    input_data: bytes | None = None,
    timeout: int = 10,
) -> subprocess.CompletedProcess[bytes]:
    """Run a command as a specific user via sudo."""
    full_cmd = ["sudo", "-u", user] + cmd
    try:
        return subprocess.run(
            full_cmd,
            capture_output=True,
            timeout=timeout,
            input=input_data,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Command timed out",
        ) from exc


def create_explorer_router(auth_dep: object) -> APIRouter:
    """Build and return the file explorer router."""
    router = APIRouter(prefix="/explorer", tags=["explorer"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    @router.get("/list")
    async def list_directory(
        path: str = Query(..., description="Absolute directory path"),
        user: str = Query(..., description="Linux username"),
        token: TokenPayload = Depends(auth_dep),
    ) -> list[FileEntry]:
        """List directory contents as the specified user."""
        _require_admin(token)
        safe_path = _validate_path(path)
        safe_user = _validate_username(user)

        # Use stat to get detailed file info
        # ls -la --time-style=+%s gives us parseable output
        result = _sudo_run(safe_user, [
            "ls", "-la", "--time-style=+%s", safe_path,
        ])

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=404, detail=stderr or "Directory not found")

        entries: list[FileEntry] = []
        lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()

        for line in lines[1:]:  # Skip "total" line
            parts = line.split(None, 6)
            if len(parts) < 7:
                continue

            perms = parts[0]
            size_str = parts[4]
            mtime_str = parts[5]
            name = parts[6]

            # Skip . and ..
            if name in (".", ".."):
                continue

            # Handle symlinks (name -> target)
            if " -> " in name:
                name = name.split(" -> ")[0]

            # Determine type
            if perms.startswith("d"):
                ftype = "dir"
            elif perms.startswith("l"):
                ftype = "symlink"
            else:
                ftype = "file"

            try:
                size = int(size_str)
            except ValueError:
                size = 0

            try:
                mtime = float(mtime_str)
            except ValueError:
                mtime = 0.0

            entries.append(FileEntry(
                name=name,
                type=ftype,
                size=size,
                permissions=perms,
                modified_at=mtime,
            ))

        return entries

    @router.get("/read")
    async def read_file(
        path: str = Query(..., description="Absolute file path"),
        user: str = Query(..., description="Linux username"),
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Read a text file as the specified user (max 1MB)."""
        _require_admin(token)
        safe_path = _validate_path(path)
        safe_user = _validate_username(user)

        # Check file size first
        stat_result = _sudo_run(safe_user, ["stat", "--format=%s", safe_path])
        if stat_result.returncode != 0:
            raise HTTPException(status_code=404, detail="File not found")

        try:
            file_size = int(stat_result.stdout.decode().strip())
        except ValueError:
            file_size = 0

        if file_size > _MAX_READ_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({file_size} bytes, max {_MAX_READ_SIZE})",
            )

        result = _sudo_run(safe_user, ["cat", safe_path])
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=404, detail=stderr or "Cannot read file")

        content = result.stdout.decode("utf-8", errors="replace")
        return {"content": content, "path": safe_path, "size": file_size}

    @router.put("/write")
    async def write_file(
        body: WriteRequest,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict[str, str]:
        """Write content to a text file as the specified user."""
        _require_admin(token)
        safe_path = _validate_path(body.path)
        safe_user = _validate_username(body.user)

        result = _sudo_run(
            safe_user,
            ["tee", safe_path],
            input_data=body.content.encode("utf-8"),
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=500, detail=stderr or "Cannot write file")

        return {"status": "ok", "path": safe_path}

    @router.post("/mkdir")
    async def mkdir(
        body: MkdirRequest,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict[str, str]:
        """Create a directory as the specified user."""
        _require_admin(token)
        safe_path = _validate_path(body.path)
        safe_user = _validate_username(body.user)

        result = _sudo_run(safe_user, ["mkdir", "-p", safe_path])
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=500, detail=stderr or "Cannot create directory")

        return {"status": "ok", "path": safe_path}

    @router.delete("/delete")
    async def delete_path(
        body: DeleteRequest,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict[str, str]:
        """Delete a file or directory as the specified user."""
        _require_admin(token)
        safe_path = _validate_path(body.path)
        safe_user = _validate_username(body.user)

        result = _sudo_run(safe_user, ["rm", "-rf", safe_path])
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=500, detail=stderr or "Cannot delete")

        return {"status": "ok", "path": safe_path}

    @router.get("/download")
    async def download_file(
        path: str = Query(..., description="Absolute file path"),
        user: str = Query(..., description="Linux username"),
        token: TokenPayload = Depends(auth_dep),
    ) -> Response:
        """Download a file (binary) as the specified user."""
        _require_admin(token)
        safe_path = _validate_path(path)
        safe_user = _validate_username(user)

        result = _sudo_run(safe_user, ["cat", safe_path], timeout=30)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise HTTPException(status_code=404, detail=stderr or "File not found")

        filename = PurePosixPath(safe_path).name
        return Response(
            content=result.stdout,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/users")
    async def get_linux_users(
        token: TokenPayload = Depends(auth_dep),
    ) -> list[dict]:
        """List available Linux users for the context switcher."""
        _require_admin(token)
        return list_linux_users()

    return router
