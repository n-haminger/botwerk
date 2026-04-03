"""File upload/download API routes for the WebUI."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.files.storage import sanitize_filename
from botwerk_bot.files.tags import guess_mime
from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.models import AgentAssignment, File
from botwerk_bot.webui.schemas import FileResponse, TokenPayload

logger = logging.getLogger(__name__)

# Default upload limit: 50 MB.
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# MIME types that are explicitly blocked.
_BLOCKED_MIMES = frozenset({
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-mach-binary",
})

# Thumbnail settings.
_THUMBNAIL_MAX_SIZE = (256, 256)
_THUMBNAIL_SUFFIX = "_thumb.webp"


def _generate_thumbnail(source: Path, dest_dir: Path) -> Path | None:
    """Create a WebP thumbnail for an image file. Returns path or None."""
    try:
        from PIL import Image

        with Image.open(source) as img:
            img.thumbnail(_THUMBNAIL_MAX_SIZE)
            thumb_name = f"{source.stem}{_THUMBNAIL_SUFFIX}"
            thumb_path = dest_dir / thumb_name
            img.save(thumb_path, format="WEBP", quality=80)
            return thumb_path
    except Exception:  # noqa: BLE001
        logger.debug("Thumbnail generation failed for %s", source, exc_info=True)
        return None


def create_file_router(
    auth_dep: object,
    upload_dir: Path,
    *,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> APIRouter:
    """Build and return the file upload/download router.

    *upload_dir* is the base directory for stored files (e.g.
    ``{botwerk_home}/webui_uploads``).  It will be created if it does not
    exist.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)

    router = APIRouter(prefix="/files", tags=["files"])

    def _file_url(file_id: int) -> str:
        return f"/api/files/{file_id}"

    def _thumbnail_url(file_id: int) -> str:
        return f"/api/files/{file_id}?thumbnail=true"

    def _to_response(f: File) -> FileResponse:
        return FileResponse(
            id=f.id,
            name=f.original_name,
            mime=f.mime_type,
            size=f.size_bytes,
            url=_file_url(f.id),
            thumbnail_url=_thumbnail_url(f.id) if f.thumbnail_path else None,
            created_at=f.created_at,
        )

    async def _check_file_access(
        user_id: int, file_obj: File, db: AsyncSession
    ) -> None:
        """Raise 403 if user cannot access this file."""
        # Owner always has access.
        if file_obj.user_id == user_id:
            return
        # Otherwise, check if user has access to the agent the file is for.
        if file_obj.agent_name:
            result = await db.execute(
                select(AgentAssignment).where(
                    AgentAssignment.user_id == user_id,
                    AgentAssignment.agent_name == file_obj.agent_name,
                )
            )
            if result.scalar_one_or_none() is not None:
                return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this file",
        )

    @router.post("/upload", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
    async def upload_file(
        file: UploadFile,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
        agent_name: str = Form(""),
    ) -> FileResponse:
        """Upload a file (multipart). Optionally associate with an agent."""
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No filename provided",
            )

        # Read the file content (enforcing size limit).
        content = await file.read()
        if len(content) > max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large (max {max_upload_bytes // (1024 * 1024)} MB)",
            )

        # Determine MIME type from content-type header or filename.
        mime = file.content_type or "application/octet-stream"
        if mime == "application/octet-stream":
            # Fallback: guess from filename.
            import mimetypes

            guessed = mimetypes.guess_type(file.filename)[0]
            if guessed:
                mime = guessed

        if mime in _BLOCKED_MIMES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File type not allowed: {mime}",
            )

        # Save to disk.
        safe_name = sanitize_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        stored_path = upload_dir / unique_name
        stored_path.write_bytes(content)

        # Generate thumbnail for images.
        thumbnail_path: Path | None = None
        if mime.startswith("image/") and not mime.endswith("/svg+xml"):
            thumbnail_path = _generate_thumbnail(stored_path, upload_dir)

        # Persist metadata.
        file_record = File(
            user_id=token.user_id,
            agent_name=agent_name,
            original_name=file.filename,
            stored_path=str(stored_path),
            mime_type=mime,
            size_bytes=len(content),
            thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        )
        db.add(file_record)
        await db.commit()
        await db.refresh(file_record)

        logger.info(
            "File uploaded: id=%d name=%s size=%d user=%d",
            file_record.id,
            file_record.original_name,
            file_record.size_bytes,
            token.user_id,
        )

        return _to_response(file_record)

    @router.get("/{file_id}")
    async def download_file(
        file_id: int,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
        thumbnail: bool = Query(False, description="Return thumbnail instead of full file"),
    ) -> FastAPIFileResponse:
        """Download a file (or its thumbnail) by ID."""
        result = await db.execute(select(File).where(File.id == file_id))
        file_record = result.scalar_one_or_none()

        if file_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found",
            )

        await _check_file_access(token.user_id, file_record, db)

        if thumbnail and file_record.thumbnail_path:
            path = Path(file_record.thumbnail_path)
            if path.is_file():
                return FastAPIFileResponse(
                    path=str(path),
                    media_type="image/webp",
                    filename=f"thumb_{file_record.original_name}.webp",
                )

        path = Path(file_record.stored_path)
        if not path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File data missing from disk",
            )

        return FastAPIFileResponse(
            path=str(path),
            media_type=file_record.mime_type,
            filename=file_record.original_name,
        )

    @router.get("", response_model=list[FileResponse])
    async def list_files(
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
        agent_name: str = Query("", description="Filter by agent name"),
    ) -> list[FileResponse]:
        """List files accessible to the current user, optionally filtered by agent."""
        query = select(File).where(File.user_id == token.user_id)
        if agent_name:
            query = query.where(File.agent_name == agent_name)
        query = query.order_by(File.created_at.desc())

        result = await db.execute(query)
        files = result.scalars().all()
        return [_to_response(f) for f in files]

    return router
