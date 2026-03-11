"""Matrix typing indicator context manager with keep-alive."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

    from nio import AsyncClient

logger = logging.getLogger(__name__)


class MatrixTypingContext:
    """Context manager that shows typing indicator in a Matrix room.

    A background keep-alive task re-sends the typing notification every
    ``interval`` seconds.  This is necessary because Matrix clients
    (e.g. Element) clear the indicator when the bot sends a message,
    and the server expires it after the timeout.

    Call :meth:`notify` after sending a message to immediately re-send
    the typing indicator and reset the keep-alive timer.
    """

    def __init__(
        self,
        client: AsyncClient,
        room_id: str,
        *,
        interval: float = 5.0,
        timeout: int = 30000,
    ) -> None:
        self._client = client
        self._room_id = room_id
        self._interval = interval
        self._timeout = timeout
        self._task: asyncio.Task[None] | None = None
        self._reset: asyncio.Event = asyncio.Event()

    async def _send_typing(self, *, source: str = "keep-alive") -> bool:
        """Send a typing notification. Returns True on success."""
        from nio import RoomTypingError

        try:
            resp = await self._client.room_typing(
                self._room_id, typing_state=True, timeout=self._timeout
            )
            if isinstance(resp, RoomTypingError):
                logger.info(
                    "room_typing(%s) error for %s: %s",
                    source,
                    self._room_id,
                    resp.status_code,
                )
                return False
            logger.info("room_typing(%s) ok for %s", source, self._room_id)
            return True
        except Exception:
            logger.warning(
                "room_typing(%s) failed for %s", source, self._room_id, exc_info=True
            )
            return False

    async def _keep_alive(self) -> None:
        """Periodically re-send typing indicator.

        Waits for ``interval`` seconds OR until :meth:`notify` is called,
        whichever comes first.  This ensures the timer resets after every
        message send, avoiding duplicate/redundant typing notifications.
        """
        while True:
            self._reset.clear()
            notified = False
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._reset.wait(), timeout=self._interval)
                notified = True
            if not notified:
                # Regular keep-alive tick — just re-send.
                await self._send_typing(source="keep-alive")

    async def notify(self) -> None:
        """Re-send typing immediately and reset the keep-alive timer.

        Call this after sending a message (which clears the typing
        indicator on the server).  Typing is re-enabled inline (in the
        caller's task) so there is no scheduling delay.  The keep-alive
        timer is reset so it doesn't fire redundantly right after.
        """
        await self._send_typing(source="notify")
        self._reset.set()

    async def __aenter__(self) -> MatrixTypingContext:
        await self._send_typing(source="enter")
        self._task = asyncio.create_task(self._keep_alive())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        try:
            await self._client.room_typing(self._room_id, typing_state=False)
        except Exception:
            logger.warning("room_typing(False) failed for %s", self._room_id, exc_info=True)
