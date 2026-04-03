"""Direct API server: WebSocket + HTTP interface for app connections.

Runs alongside the bot.  Designed for use
over Tailscale (default) or other private networks so that no traffic
passes through third-party servers.

WebSocket protocol (E2E encrypted)
-----------------------------------
1. Client connects to ``ws://<host>:<port>/ws``
2. Client sends ``{"type": "auth", "token": "...", "e2e_pk": "<b64>"}``
   (optional ``"chat_id": N`` to override default session)
3. Server responds ``{"type": "auth_ok", "chat_id": N, "e2e_pk": "<b64>", "providers": [...], "active_provider": "...", "active_model": "..."}``
4. All subsequent frames are E2E encrypted: ``base64(nonce_24 + ciphertext)``
5. Encrypted message: ``{"type": "message", "text": "..."}``
   Server streams back encrypted events:
     - ``{"type": "text_delta",     "data": "..."}``
     - ``{"type": "tool_activity",  "data": "..."}``
     - ``{"type": "system_status",  "data": "..."}``
     - ``{"type": "result", "text": "...", "stream_fallback": bool, "files": [...]}``
6. Encrypted abort: ``{"type": "abort"}`` (or ``/stop`` as message text)
   Server responds ``{"type": "abort_ok", "killed": N}``

HTTP polling fallback
---------------------
- ``GET  /poll?chat_id=N&after=S``  -- poll buffered events after seq *S*
- ``POST /send``                    -- send a message when WS is unavailable

HTTP endpoints
--------------
- ``GET  /health``              -- health check
- ``GET  /files?path=<abs>``    -- download a file (Bearer token auth)
- ``POST /upload``              -- upload a file (Bearer token auth, multipart)
- ``POST /upload/multi``        -- upload multiple files (Bearer token auth, multipart)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from starlette.datastructures import UploadFile as StarletteUploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.websockets import WebSocketState

from botwerk_bot.api.crypto import E2ESession
from botwerk_bot.bus.lock_pool import LockPool
from botwerk_bot.files.prompt import MediaInfo, build_media_prompt
from botwerk_bot.files.storage import prepare_destination, sanitize_filename
from botwerk_bot.files.tags import (
    classify_mime,
    extract_file_paths,
    guess_mime,
    is_image_path,
    path_from_file_tag,
)
from botwerk_bot.log_context import set_log_context
from botwerk_bot.security.paths import is_path_safe
from botwerk_bot.session.key import SessionKey

if TYPE_CHECKING:
    from botwerk_bot.config import ApiConfig

logger = logging.getLogger(__name__)

# Callback types matching Orchestrator.handle_message_streaming / abort
StreamingMessageHandler = Callable[..., Awaitable[Any]]
AbortHandler = Callable[[int], Awaitable[int]]

_DEFAULT_MAX_UPLOAD_MB = 100

# -- Event buffer for HTTP polling fallback --------------------------------

_BUFFER_SIZE = 200
_BUFFER_TTL_S = 300  # 5 minutes


class _EventBuffer:
    """Per-chat ring buffer that stores recent plaintext events for HTTP polling.

    Events are plain dicts (NOT encrypted).  The poll endpoint returns them
    as-is -- encryption is the proxy's responsibility, not ours.
    """

    __slots__ = ("_buf", "_last_access", "_seq")

    def __init__(self) -> None:
        self._buf: list[tuple[int, dict[str, object]]] = []
        self._seq: int = 0
        self._last_access: float = time.monotonic()

    @property
    def seq(self) -> int:
        return self._seq

    def push(self, event: dict[str, object]) -> int:
        """Append an event and return its sequence number."""
        self._seq += 1
        self._buf.append((self._seq, event))
        if len(self._buf) > _BUFFER_SIZE:
            self._buf.pop(0)
        self._last_access = time.monotonic()
        return self._seq

    def after(self, seq: int) -> list[dict[str, object]]:
        """Return all events with seq > *seq*, wrapped with their seq number."""
        self._last_access = time.monotonic()
        return [
            {**evt, "_seq": s} for s, evt in self._buf if s > seq
        ]

    def clear(self) -> None:
        """Discard all buffered events and reset the sequence counter."""
        self._buf.clear()
        self._seq = 0
        self._last_access = time.monotonic()

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self._last_access) > _BUFFER_TTL_S


class _UploadTooLarge(Exception):
    """Internal sentinel raised when cumulative upload size exceeds the limit."""


def _detect_tailscale() -> bool:
    """Return True if the ``tailscale`` binary is found in PATH."""
    return shutil.which("tailscale") is not None


class _SecureChannel:
    """Encrypted WebSocket channel for post-auth communication."""

    __slots__ = ("_e2e", "ws")

    def __init__(self, ws: WebSocket, e2e: E2ESession) -> None:
        self.ws = ws
        self._e2e = e2e

    @property
    def closed(self) -> bool:
        return self.ws.client_state != WebSocketState.CONNECTED

    async def send(self, data: dict[str, object]) -> bool:
        """Encrypt and send.  Returns False if connection lost."""
        if self.closed:
            return False
        try:
            await self.ws.send_text(self._e2e.encrypt(data))
        except (ConnectionResetError, ConnectionError, RuntimeError, WebSocketDisconnect):
            return False
        return True

    def decrypt(self, frame: str) -> dict[str, Any]:
        """Decrypt an incoming encrypted frame."""
        return self._e2e.decrypt(frame)


class _NullChannel:
    """Dummy channel for HTTP-dispatched messages (no WebSocket to send to)."""

    @property
    def closed(self) -> bool:
        return True

    async def send(self, data: dict[str, object]) -> bool:
        return False

    def decrypt(self, frame: str) -> dict[str, Any]:
        raise RuntimeError("_NullChannel cannot decrypt")


class _StreamCallbacks:
    """Streaming callbacks that forward orchestrator events to a WebSocket AND event buffer."""

    __slots__ = ("_buffer_fn", "channel", "disconnected")

    def __init__(
        self,
        channel: _SecureChannel | _NullChannel,
        buffer_fn: Callable[[dict[str, object]], int] | None = None,
    ) -> None:
        self.channel: _SecureChannel | _NullChannel = channel
        self.disconnected = False
        self._buffer_fn = buffer_fn

    def _buffer(self, event: dict[str, object]) -> None:
        if self._buffer_fn is not None:
            self._buffer_fn(event)

    async def on_text(self, delta: str) -> None:
        event: dict[str, object] = {"type": "text_delta", "data": delta}
        self._buffer(event)
        if self.disconnected:
            return
        if not await self.channel.send(event):
            self.disconnected = True

    async def on_tool(self, name: str) -> None:
        event: dict[str, object] = {"type": "tool_activity", "data": name}
        self._buffer(event)
        if self.disconnected:
            return
        if not await self.channel.send(event):
            self.disconnected = True

    async def on_system(self, label: str | None) -> None:
        event: dict[str, object] = {"type": "system_status", "data": label}
        self._buffer(event)
        if self.disconnected:
            return
        if not await self.channel.send(event):
            self.disconnected = True


def _parse_file_refs(text: str) -> list[dict[str, object]]:
    """Extract ``<file:...>`` tags and return metadata for the app."""
    refs: list[dict[str, object]] = []
    for fp in extract_file_paths(text):
        p = path_from_file_tag(fp)
        refs.append(
            {
                "path": str(p),
                "name": p.name,
                "is_image": is_image_path(str(p)),
            }
        )
    return refs


class ApiServer:
    """WebSocket API server for direct app connections.

    Provides direct orchestrator access via WebSocket/HTTP.
    All handler wiring is done via setter methods so the server module
    has zero imports from the orchestrator (no coupling).
    """

    def __init__(
        self,
        config: ApiConfig,
        *,
        default_chat_id: int = 0,
        lock_pool: LockPool | None = None,
    ) -> None:
        self._config = config
        self._default_chat_id = default_chat_id
        self._max_upload_bytes = getattr(config, "max_upload_mb", _DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024
        self._handle_message: StreamingMessageHandler | None = None
        self._handle_abort: AbortHandler | None = None
        self._server: uvicorn.Server | None = None
        self._lock_pool = lock_pool if lock_pool is not None else LockPool()
        self._active_ws: set[WebSocket] = set()
        self._event_buffers: dict[int, _EventBuffer] = {}
        # File context (set via set_file_context)
        self._allowed_roots: Sequence[Path] | None = None
        self._upload_dir: Path | None = None
        self._workspace: Path | None = None
        self._provider_info: list[dict[str, object]] = []
        self._active_state_getter: Callable[[], tuple[str, str]] | None = None

        # Build FastAPI app
        self._app = FastAPI()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register all HTTP and WebSocket routes on the FastAPI app."""
        self._app.get("/health")(self._handle_health)
        self._app.get("/files", response_model=None)(self._handle_file_download)
        self._app.post("/upload", response_model=None)(self._handle_file_upload)
        self._app.post("/upload/multi", response_model=None)(self._handle_multi_file_upload)
        self._app.get("/poll")(self._handle_poll)
        self._app.post("/send")(self._handle_send)
        self._app.websocket("/ws")(self._handle_websocket)

    # -- Handler wiring --------------------------------------------------------

    def set_message_handler(self, handler: StreamingMessageHandler) -> None:
        """Orchestrator.handle_message_streaming (bound method)."""
        self._handle_message = handler

    def set_abort_handler(self, handler: AbortHandler) -> None:
        """Orchestrator.abort (bound method)."""
        self._handle_abort = handler

    def set_file_context(
        self,
        *,
        allowed_roots: Sequence[Path] | None,
        upload_dir: Path,
        workspace: Path,
    ) -> None:
        """Configure file download/upload paths."""
        self._allowed_roots = allowed_roots
        self._upload_dir = upload_dir
        self._workspace = workspace

    def set_provider_info(self, providers: list[dict[str, object]]) -> None:
        """Set the list of authenticated providers for auth_ok responses."""
        self._provider_info = providers

    def set_active_state_getter(self, getter: Callable[[], tuple[str, str]]) -> None:
        """Set a callback that returns (active_provider, active_model)."""
        self._active_state_getter = getter

    # -- Lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        """Create the FastAPI app and start listening via Uvicorn."""
        if not _detect_tailscale() and not self._config.allow_public:
            logger.warning(
                "API server: Tailscale NOT detected. Your API may be exposed "
                "to the public internet on %s:%d. Install Tailscale for secure "
                "private networking, or set api.allow_public=true in config to "
                "acknowledge this risk.",
                self._config.host,
                self._config.port,
            )

        uv_config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(uv_config)
        # Run in background task so it doesn't block
        asyncio.ensure_future(self._server.serve())
        # Wait briefly for the server to start
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        logger.info(
            "API server listening on %s:%d",
            self._config.host,
            self._config.port,
        )

    async def stop(self) -> None:
        """Close all connections and shut down the server."""
        for ws in list(self._active_ws):
            try:
                await ws.close(code=1001, reason="server shutdown")
            except Exception:
                pass
        self._active_ws.clear()
        if self._server:
            self._server.should_exit = True
            # Give uvicorn a moment to shut down
            await asyncio.sleep(0.1)
            self._server = None
        logger.info("API server stopped")

    # -- Event buffer ----------------------------------------------------------

    def _get_buffer(self, chat_id: int) -> _EventBuffer:
        """Get or create the event buffer for a chat.  Prunes expired buffers."""
        buf = self._event_buffers.get(chat_id)
        if buf is None:
            buf = _EventBuffer()
            self._event_buffers[chat_id] = buf
        # Lazy prune: clean up expired buffers occasionally
        if len(self._event_buffers) > 50:
            expired = [k for k, v in self._event_buffers.items() if v.expired]
            for k in expired:
                del self._event_buffers[k]
        return buf

    def _buffer_event(self, chat_id: int, event: dict[str, object]) -> int:
        """Push an event into the chat's buffer. Returns the seq number."""
        return self._get_buffer(chat_id).push(event)

    def clear_buffer(self, chat_id: int) -> None:
        """Clear the event buffer for a specific chat, discarding old events."""
        buf = self._event_buffers.get(chat_id)
        if buf is not None:
            buf.clear()

    # -- Bearer token auth for HTTP endpoints ----------------------------------

    def _verify_bearer(self, request: Request) -> bool:
        """Check ``Authorization: Bearer <token>`` header."""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:], self._config.token)

    # -- HTTP handlers ---------------------------------------------------------

    async def _handle_health(self) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "connections": len(self._active_ws),
            }
        )

    async def _handle_file_download(self, request: Request, path: str = Query("")) -> JSONResponse | FileResponse:  # noqa: E501
        """Serve a file from the filesystem (Bearer token auth, path validation)."""
        if not self._verify_bearer(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if not path:
            return JSONResponse({"error": "missing 'path' query parameter"}, status_code=400)

        file_path = Path(path)
        if self._allowed_roots is not None and not is_path_safe(file_path, self._allowed_roots):
            return JSONResponse({"error": "path outside allowed roots"}, status_code=403)

        if not await asyncio.to_thread(file_path.is_file):
            return JSONResponse({"error": "file not found"}, status_code=404)

        mime = guess_mime(file_path)
        return FileResponse(file_path, media_type=mime)

    async def _handle_file_upload(self, request: Request, file: UploadFile | None = None, caption: str | None = None) -> JSONResponse:
        """Accept a multipart file upload and return the saved path + prompt."""
        if not self._verify_bearer(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if self._upload_dir is None or self._workspace is None:
            return JSONResponse({"error": "file uploads not configured"}, status_code=503)

        if file is None:
            return JSONResponse({"error": "expected a 'file' field"}, status_code=400)

        raw_name = file.filename or "upload"
        safe_name = sanitize_filename(raw_name)

        dest = await asyncio.to_thread(prepare_destination, self._upload_dir, safe_name)

        total = 0
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > self._max_upload_bytes:
                    dest.unlink(missing_ok=True)
                    return JSONResponse(
                        {"error": f"file exceeds {self._max_upload_bytes // (1024 * 1024)} MB limit"},
                        status_code=413,
                    )
                f.write(chunk)

        # Detect actual MIME from saved file content (magic bytes + extension fallback)
        mime = await asyncio.to_thread(guess_mime, dest)

        # Read optional caption from form field
        if caption is None:
            # Try reading from form data directly
            form = await request.form()
            caption_field = form.get("caption")
            if caption_field is not None:
                caption = str(caption_field)

        info = MediaInfo(
            path=dest,
            media_type=mime,
            file_name=dest.name,
            caption=caption,
            original_type=classify_mime(mime),
        )
        prompt = build_media_prompt(info, self._workspace, transport="API")

        logger.info("API upload: %s (%s, %d bytes)", dest.name, mime, total)
        return JSONResponse(
            {
                "path": str(dest),
                "name": dest.name,
                "mime": mime,
                "size": total,
                "prompt": prompt,
            }
        )

    async def _handle_multi_file_upload(self, request: Request) -> JSONResponse:
        """Accept multiple files in a single multipart upload.

        Each ``file`` field is saved independently.  An optional ``caption``
        field (anywhere in the stream) is attached to every file's prompt.
        Returns a JSON object with a ``files`` list and a combined ``prompt``.
        """
        if not self._verify_bearer(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if self._upload_dir is None or self._workspace is None:
            return JSONResponse({"error": "file uploads not configured"}, status_code=503)

        try:
            form = await request.form()
        except Exception:
            return JSONResponse({"error": "multipart body required"}, status_code=400)

        saved: list[dict[str, Any]] = []
        caption: str | None = None
        cumulative_bytes = 0

        # Extract caption if present
        caption_field = form.get("caption")
        if caption_field is not None:
            caption = str(caption_field)

        # Process all file fields — Starlette's multi_items() yields all entries
        for field_name, upload in form.multi_items():
            if field_name == "caption" or field_name != "file":
                continue
            if not isinstance(upload, (UploadFile, StarletteUploadFile)):
                continue

            raw_name = upload.filename or "upload"
            safe_name = sanitize_filename(raw_name)

            dest = await asyncio.to_thread(prepare_destination, self._upload_dir, safe_name)

            file_bytes = 0
            try:
                with dest.open("wb") as f:
                    while True:
                        chunk = await upload.read(65536)
                        if not chunk:
                            break
                        file_bytes += len(chunk)
                        cumulative_bytes += len(chunk)
                        if cumulative_bytes > self._max_upload_bytes:
                            raise _UploadTooLarge
                        await asyncio.to_thread(f.write, chunk)
            except _UploadTooLarge:
                dest.unlink(missing_ok=True)
                # Clean up already-saved files from this request.
                for entry in saved:
                    Path(entry["path"]).unlink(missing_ok=True)
                return JSONResponse(
                    {"error": f"total upload exceeds {self._max_upload_bytes // (1024 * 1024)} MB limit"},
                    status_code=413,
                )

            mime = await asyncio.to_thread(guess_mime, dest)
            saved.append({
                "path": str(dest),
                "name": dest.name,
                "mime": mime,
                "size": file_bytes,
            })
            logger.info("API multi-upload: %s (%s, %d bytes)", dest.name, mime, file_bytes)

        if not saved:
            return JSONResponse({"error": "no files received"}, status_code=400)

        # Build individual MediaInfo objects and combine prompts.
        prompts: list[str] = []
        for entry in saved:
            info = MediaInfo(
                path=Path(entry["path"]),
                media_type=entry["mime"],
                file_name=entry["name"],
                caption=caption,
                original_type=classify_mime(entry["mime"]),
            )
            prompts.append(build_media_prompt(info, self._workspace, transport="API"))

        combined_prompt = "\n---\n".join(prompts)

        return JSONResponse({
            "files": saved,
            "prompt": combined_prompt,
            "total_size": cumulative_bytes,
        })

    # -- HTTP polling + send fallback ------------------------------------------

    async def _handle_poll(self, request: Request, chat_id: int = Query(None), after: int = Query(0)) -> JSONResponse:
        """Return buffered events for a chat after a given sequence number.

        ``GET /poll?chat_id=N&after=S``  (Bearer token auth)
        """
        if not self._verify_bearer(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if chat_id is None:
            return JSONResponse({"error": "chat_id required (integer)"}, status_code=400)

        buf = self._event_buffers.get(chat_id)
        if buf is None:
            return JSONResponse({"seq": 0, "events": []})

        events = buf.after(after)
        return JSONResponse({"seq": buf.seq, "events": events})

    async def _handle_send(self, request: Request) -> JSONResponse:
        """Accept a message via HTTP POST when WebSocket is unavailable.

        ``POST /send``  JSON body: ``{"chat_id": N, "text": "..."}``
        Bearer token auth.  The response is NOT streamed -- the client must
        poll ``/poll`` to receive streaming events and the final result.
        """
        if not self._verify_bearer(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        chat_id = body.get("chat_id", self._default_chat_id)
        if not isinstance(chat_id, int) or chat_id <= 0:
            chat_id = self._default_chat_id

        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "empty message"}, status_code=400)

        if not self._handle_message:
            return JSONResponse({"error": "handler not configured"}, status_code=503)

        channel_id = body.get("channel_id")
        if not isinstance(channel_id, int) or channel_id <= 0:
            channel_id = None
        key = SessionKey(chat_id=chat_id, topic_id=channel_id)

        lock = self._lock_pool.get(key.lock_key)

        # Intercept /stop
        if text.lower() == "/stop":
            killed = 0
            if self._handle_abort:
                killed = await self._handle_abort(chat_id)
            self._buffer_event(chat_id, {"type": "abort_ok", "killed": killed})
            return JSONResponse({"accepted": True, "type": "abort"})

        # Fire-and-forget: dispatch in background so we can return 202 immediately
        async def _run() -> None:
            async with lock:
                set_log_context(operation="api-http", chat_id=key.chat_id)
                await self._dispatch_message_http(key, text)

        asyncio.ensure_future(_run())

        buf = self._get_buffer(chat_id)
        return JSONResponse({"accepted": True, "seq": buf.seq}, status_code=202)

    async def _dispatch_message_http(
        self,
        key: SessionKey,
        text: str,
    ) -> None:
        """Dispatch a message from HTTP /send -- results go only to the event buffer."""
        assert self._handle_message is not None

        def buf(event: dict[str, object]) -> int:
            return self._buffer_event(key.chat_id, event)

        # Create a dummy channel that never sends (no WS)
        callbacks = _StreamCallbacks(_NullChannel(), buffer_fn=buf)

        try:
            result = await self._handle_message(
                key,
                text,
                on_text_delta=callbacks.on_text,
                on_tool_activity=callbacks.on_tool,
                on_system_status=callbacks.on_system,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("API HTTP dispatch error key=%s", key.storage_key)
            buf({"type": "error", "code": "internal_error", "message": "An internal error occurred"})
            return

        if result is None:
            return

        files = _parse_file_refs(result.text)
        buf({
            "type": "result",
            "text": result.text,
            "stream_fallback": result.stream_fallback,
            "files": files,
        })

    # -- WebSocket handlers ----------------------------------------------------

    async def _handle_websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        logger.info("API WebSocket opened from %s", websocket.client)

        auth_result = await self._authenticate(websocket)
        if auth_result is None:
            return

        key, e2e = auth_result
        channel = _SecureChannel(websocket, e2e)

        self._active_ws.add(websocket)
        try:
            await self._session_loop(channel, key)
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass
        finally:
            self._active_ws.discard(websocket)
            logger.info("API WebSocket closed key=%s", key.storage_key)

    # -- Authentication --------------------------------------------------------

    async def _ws_send(self, ws: WebSocket, data: dict[str, object]) -> bool:
        """Send plaintext JSON to a WebSocket (auth phase only).  Returns False on disconnect."""
        try:
            await ws.send_json(data)
        except (ConnectionResetError, ConnectionError, RuntimeError, WebSocketDisconnect):
            return False
        return True

    async def _ws_reject(self, ws: WebSocket, code: str, message: str) -> None:
        """Send an error response and close the WebSocket."""
        await self._ws_send(ws, {"type": "error", "code": code, "message": message})
        try:
            await ws.close()
        except Exception:
            pass

    async def _read_auth_message(self, ws: WebSocket) -> dict[str, object] | None:
        """Read and validate the initial auth message. Returns parsed data or None."""
        try:
            raw = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
        except (TimeoutError, asyncio.CancelledError, WebSocketDisconnect):
            await self._ws_reject(ws, "auth_timeout", "No auth message within 10 s")
            return None
        except (json.JSONDecodeError, ValueError):
            await self._ws_reject(ws, "auth_required", "First message must be JSON text")
            return None

        if not isinstance(raw, dict) or raw.get("type") != "auth":
            await self._ws_reject(ws, "auth_required", "First message must be auth JSON")
            return None

        return raw

    async def _authenticate(
        self,
        ws: WebSocket,
    ) -> tuple[SessionKey, E2ESession] | None:
        """Wait for auth + E2E key exchange.  Returns (key, e2e) or None."""
        data = await self._read_auth_message(ws)
        if data is None:
            return None

        token = str(data.get("token", ""))
        if not hmac.compare_digest(token, self._config.token):
            logger.warning("API auth failed (invalid token)")
            await self._ws_reject(ws, "auth_failed", "Invalid token")
            return None

        # E2E key exchange (mandatory)
        e2e = E2ESession()
        e2e_pk = data.get("e2e_pk")
        e2e_valid = isinstance(e2e_pk, str) and bool(e2e_pk)
        if e2e_valid:
            try:
                assert isinstance(e2e_pk, str)
                e2e.set_remote_key(e2e_pk)
            except Exception:
                e2e_valid = False
        if not e2e_valid:
            await self._ws_reject(ws, "auth_failed", "e2e_pk required or invalid")
            return None

        chat_id = data.get("chat_id", self._default_chat_id)
        if not isinstance(chat_id, int) or chat_id <= 0:
            chat_id = self._default_chat_id

        # Optional channel_id for per-channel session isolation (maps to topic_id)
        channel_id = data.get("channel_id")
        if not isinstance(channel_id, int) or channel_id <= 0:
            channel_id = None

        key = SessionKey(chat_id=chat_id, topic_id=channel_id)

        # Last plaintext message -- everything after this is E2E encrypted
        auth_ok_payload: dict[str, object] = {
            "type": "auth_ok",
            "chat_id": chat_id,
            "e2e_pk": e2e.local_pk_b64,
            "providers": self._provider_info,
        }
        if channel_id is not None:
            auth_ok_payload["channel_id"] = channel_id
        if self._active_state_getter:
            active_provider, active_model = self._active_state_getter()
            auth_ok_payload["active_provider"] = active_provider
            auth_ok_payload["active_model"] = active_model
        await self._ws_send(ws, auth_ok_payload)
        logger.info("API client authenticated key=%s (E2E)", key.storage_key)
        return key, e2e

    # -- Session loop ----------------------------------------------------------

    async def _session_loop(
        self,
        channel: _SecureChannel,
        key: SessionKey,
    ) -> None:
        """Read encrypted messages from the client and dispatch them sequentially."""
        lock = self._lock_pool.get(key.lock_key)
        set_log_context(operation="api", chat_id=key.chat_id)

        while True:
            try:
                msg = await channel.ws.receive_text()
            except WebSocketDisconnect:
                break
            except RuntimeError:
                # WebSocket already closed
                break
            await self._route_text_message(channel, msg, key, lock)

    async def _route_text_message(
        self,
        channel: _SecureChannel,
        raw_data: str,
        key: SessionKey,
        lock: asyncio.Lock,
    ) -> None:
        """Decrypt and route a single encrypted text frame."""
        try:
            data = channel.decrypt(raw_data)
        except Exception:
            logger.warning("E2E decryption failed key=%s", key.storage_key)
            await channel.send(
                {
                    "type": "error",
                    "code": "decrypt_failed",
                    "message": "Decryption failed",
                },
            )
            return

        msg_type = str(data.get("type", ""))

        if msg_type == "message":
            text = str(data.get("text", "")).strip()
            if not text:
                await channel.send(
                    {
                        "type": "error",
                        "code": "empty",
                        "message": "Empty message",
                    },
                )
                return
            # Intercept /stop since the orchestrator doesn't handle it
            if text.lower() == "/stop":
                await self._dispatch_abort(channel, key.chat_id)
                return
            async with lock:
                set_log_context(operation="api", chat_id=key.chat_id)
                await self._dispatch_message(channel, key, text)

        elif msg_type == "abort":
            await self._dispatch_abort(channel, key.chat_id)

        else:
            await channel.send(
                {
                    "type": "error",
                    "code": "unknown_type",
                    "message": f"Unknown message type: {msg_type}",
                },
            )

    # -- Dispatch --------------------------------------------------------------

    async def _dispatch_message(
        self,
        channel: _SecureChannel,
        key: SessionKey,
        text: str,
    ) -> None:
        """Route a message through the orchestrator with encrypted streaming callbacks."""
        if not self._handle_message:
            await channel.send(
                {
                    "type": "error",
                    "code": "no_handler",
                    "message": "Message handler not configured",
                },
            )
            return

        def buf(event: dict[str, object]) -> int:
            return self._buffer_event(key.chat_id, event)

        callbacks = _StreamCallbacks(channel, buffer_fn=buf)
        result = await self._execute_streaming(key, text, callbacks)
        if result is None:
            return

        if callbacks.disconnected:
            logger.info(
                "API client disconnected mid-stream key=%s -- sending result anyway",
                key.storage_key,
            )

        # Parse file references from the response for the app
        files = _parse_file_refs(result.text)

        result_event: dict[str, object] = {
            "type": "result",
            "text": result.text,
            "stream_fallback": result.stream_fallback,
            "files": files,
        }
        buf(result_event)
        await channel.send(result_event)

    async def _execute_streaming(
        self,
        key: SessionKey,
        text: str,
        callbacks: _StreamCallbacks,
    ) -> Any:
        """Call the orchestrator handler, return result or None on error."""
        assert self._handle_message is not None
        try:
            return await self._handle_message(
                key,
                text,
                on_text_delta=callbacks.on_text,
                on_tool_activity=callbacks.on_tool,
                on_system_status=callbacks.on_system,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("API dispatch error key=%s", key.storage_key)
            await callbacks.channel.send(
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": "An internal error occurred",
                },
            )
            return None

    async def _dispatch_abort(
        self,
        channel: _SecureChannel,
        chat_id: int,
    ) -> None:
        """Abort running CLI processes for this chat."""
        killed = 0
        if self._handle_abort:
            killed = await self._handle_abort(chat_id)
        event: dict[str, object] = {"type": "abort_ok", "killed": killed}
        self._buffer_event(chat_id, event)
        await channel.send(event)
