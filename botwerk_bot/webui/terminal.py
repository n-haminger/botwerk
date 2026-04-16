"""PTY-based web terminal with WebSocket transport.

Spawns a shell under a selected Linux user and bridges I/O via WebSocket.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from botwerk_bot.webui.auth import COOKIE_NAME, decode_token
from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)

# Maximum bytes to read from PTY per iteration
_READ_SIZE = 4096
# Poll interval for PTY output (seconds)
_POLL_INTERVAL = 0.02
# Max SIGTERM grace period before SIGKILL (seconds)
_CLOSE_GRACE_SECONDS = 2.0
# PTY dimension bounds (xterm defaults are 80x24; most terminals <= 500)
_MIN_PTY_DIM = 1
_MAX_PTY_DIM = 500

_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


class TerminalSession:
    """Manages a single PTY session for a Linux user."""

    def __init__(
        self,
        user: str,
        cols: int = 80,
        rows: int = 24,
        *,
        argv: list[str] | None = None,
    ) -> None:
        self.user = user
        self.cols = cols
        self.rows = rows
        self.master_fd: int | None = None
        self.pid: int | None = None
        self._closed = False
        # ``argv`` is injectable for tests so we can spawn /bin/cat instead
        # of a real user shell.  Production defaults to ``sudo -u <user> -i``.
        self._argv = argv if argv is not None else [
            "sudo", "-u", self.user, "--login", "-i",
        ]

    def start(self) -> None:
        """Fork a PTY and exec the target command (``sudo -u`` by default)."""
        pid, fd = pty.fork()

        if pid == 0:
            # Child process: exec the target command.  ``pty.fork`` has
            # already wired stdin/stdout/stderr to the slave side; we only
            # need to exec.  Any failure must exit immediately — otherwise
            # the child would continue as a Python interpreter.
            try:
                os.execvp(self._argv[0], self._argv)
            except Exception as exc:  # noqa: BLE001
                try:
                    os.write(
                        2,
                        f"terminal: exec failed: {exc}\r\n".encode(),
                    )
                except OSError:
                    pass
                os._exit(127)

        # Parent: keep the PID and master fd for I/O.
        self.pid = pid
        self.master_fd = fd

        # Initial window size + non-blocking reads.
        self.resize(self.cols, self.rows)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def resize(self, cols: int, rows: int) -> None:
        """Send TIOCSWINSZ to resize the terminal.

        Invalid types or out-of-range values are silently clamped rather
        than propagating struct/TypeError up to the WebSocket handler.
        """
        if self.master_fd is None:
            return
        cols = _clamp_pty_dim(cols, self.cols)
        rows = _clamp_pty_dim(rows, self.rows)
        self.cols = cols
        self.rows = rows
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            # fd closed underneath us — mark dead and stop.
            self._closed = True
            return
        # Signal the child process group about the resize
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGWINCH)
            except OSError:
                pass

    def write(self, data: str) -> None:
        """Write input data to the PTY."""
        if self.master_fd is None or self._closed:
            return
        try:
            os.write(self.master_fd, data.encode())
        except OSError:
            self._closed = True

    def read(self) -> str | None:
        """Non-blocking read from PTY. Returns None if no data available."""
        if self.master_fd is None or self._closed:
            return None
        try:
            ready, _, _ = select.select([self.master_fd], [], [], 0)
            if ready:
                data = os.read(self.master_fd, _READ_SIZE)
                if not data:
                    self._closed = True
                    return None
                return data.decode("utf-8", errors="replace")
        except OSError:
            self._closed = True
        return None

    def is_alive(self) -> bool:
        """Check if the child process is still running."""
        if self.pid is None or self._closed:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid != 0:
                self._closed = True
                return False
            return True
        except ChildProcessError:
            self._closed = True
            return False

    def close(self) -> int:
        """Terminate the session and return exit code.

        Uses non-blocking ``waitpid(WNOHANG)`` with a bounded grace period
        so the caller (async handler) cannot deadlock on an unkillable
        child.  Escalates SIGTERM -> SIGKILL if the child does not exit.
        """
        exit_code = 0
        pid = self.pid
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.monotonic() + _CLOSE_GRACE_SECONDS
            reaped = False
            while time.monotonic() < deadline:
                try:
                    wpid, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    reaped = True
                    break
                except OSError:
                    break
                if wpid != 0:
                    exit_code = (
                        os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                    )
                    reaped = True
                    break
                time.sleep(0.02)
            if not reaped:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    _, status = os.waitpid(pid, 0)
                    exit_code = (
                        os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                    )
                except (OSError, ChildProcessError):
                    pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        self.master_fd = None
        self.pid = None
        self._closed = True
        return exit_code

    @property
    def closed(self) -> bool:
        return self._closed


class TerminalWebSocket:
    """Handles a WebSocket connection for terminal I/O."""

    def __init__(self, secret_key: str) -> None:
        self._secret = secret_key

    async def handle(self, websocket: WebSocket) -> None:
        """Full lifecycle: authenticate, initialize PTY, bridge I/O."""
        token = self._authenticate(websocket)
        if token is None or not token.is_admin:
            await websocket.close(code=4001, reason="Admin authentication required")
            return

        await websocket.accept()

        session: TerminalSession | None = None
        try:
            # Wait for init message
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            msg = json.loads(raw)
            if msg.get("type") != "init":
                await self._send(websocket, {"type": "error", "data": "Expected init message"})
                await websocket.close(code=4002, reason="Expected init message")
                return

            user = msg.get("user", "root")
            cols = msg.get("cols", 80)
            rows = msg.get("rows", 24)

            # Validate user string (prevent injection)
            if not _is_safe_username(user):
                await self._send(websocket, {"type": "error", "data": "Invalid username"})
                await websocket.close(code=4003, reason="Invalid username")
                return

            session = TerminalSession(user, cols, rows)
            session.start()

            # Start output reader task
            output_task = asyncio.create_task(
                self._read_output(websocket, session)
            )

            # Read input from WebSocket
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")
                    if msg_type == "input":
                        data = msg.get("data", "")
                        if data:
                            session.write(data)
                    elif msg_type == "resize":
                        session.resize(
                            msg.get("cols", session.cols),
                            msg.get("rows", session.rows),
                        )
                    elif msg_type == "init":
                        # Switch user: close old session, start new.
                        # ``close()`` may block (waitpid), so run off-loop.
                        exit_code = await asyncio.to_thread(session.close)
                        output_task.cancel()
                        try:
                            await output_task
                        except asyncio.CancelledError:
                            pass

                        user = msg.get("user", "root")
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)

                        if not _is_safe_username(user):
                            await self._send(websocket, {
                                "type": "error",
                                "data": "Invalid username",
                            })
                            continue

                        session = TerminalSession(user, cols, rows)
                        session.start()
                        output_task = asyncio.create_task(
                            self._read_output(websocket, session)
                        )

            except WebSocketDisconnect:
                pass
            finally:
                output_task.cancel()
                try:
                    await output_task
                except asyncio.CancelledError:
                    pass

        except asyncio.TimeoutError:
            try:
                await websocket.close(code=4004, reason="Init timeout")
            except Exception:  # noqa: BLE001
                pass
        except Exception:
            logger.exception("Terminal WebSocket error")
            try:
                await websocket.close(code=1011, reason="Internal error")
            except Exception:  # noqa: BLE001
                pass
        finally:
            if session is not None:
                # ``close()`` may block (waitpid), so run off-loop.
                exit_code = await asyncio.to_thread(session.close)
                try:
                    await self._send(websocket, {"type": "exit", "code": exit_code})
                except Exception:  # noqa: BLE001
                    pass

    async def _read_output(
        self, websocket: WebSocket, session: TerminalSession
    ) -> None:
        """Continuously read PTY output and send to WebSocket."""
        while not session.closed:
            data = session.read()
            if data:
                await self._send(websocket, {"type": "output", "data": data})
            elif not session.is_alive():
                break
            else:
                await asyncio.sleep(_POLL_INTERVAL)

    def _authenticate(self, websocket: WebSocket) -> TokenPayload | None:
        """Read JWT from cookie. Returns None on failure."""
        token_value = websocket.cookies.get(COOKIE_NAME)
        if not token_value:
            return None
        try:
            return decode_token(token_value, self._secret)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    async def _send(websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send JSON, silently ignoring closed connections."""
        try:
            await websocket.send_json(data)
        except Exception:  # noqa: BLE001
            pass


def _is_safe_username(username: str) -> bool:
    """Validate that a username contains only safe characters."""
    if not isinstance(username, str) or not username or len(username) > 64:
        return False
    return bool(_USERNAME_RE.match(username))


def _clamp_pty_dim(value: Any, fallback: int) -> int:
    """Clamp a PTY dimension (cols/rows) into a safe range.

    Rejects non-int/bool inputs and clamps integers to ``_MIN_PTY_DIM ..
    _MAX_PTY_DIM``.  ``struct.pack("HHHH", ...)`` requires ``0 <= x <
    65536``; the clamp is stricter than that to avoid pathological values.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    if value < _MIN_PTY_DIM:
        return _MIN_PTY_DIM
    if value > _MAX_PTY_DIM:
        return _MAX_PTY_DIM
    return value
