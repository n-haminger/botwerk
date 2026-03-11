"""Tests for MatrixTypingContext (Matrix typing indicator with keep-alive)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def _make_client(success: bool = True) -> MagicMock:
    """Create a mock nio AsyncClient with room_typing."""
    client = MagicMock()
    if success:
        resp = MagicMock()
        resp.__class__ = type("RoomTypingResponse", (), {})
        client.room_typing = AsyncMock(return_value=resp)
    else:
        from nio import RoomTypingError

        err = RoomTypingError.__new__(RoomTypingError)
        err.status_code = "M_LIMIT_EXCEEDED"
        client.room_typing = AsyncMock(return_value=err)
    return client


ROOM = "!test:example.com"


class TestMatrixTypingContext:
    """Test the Matrix typing indicator context manager."""

    async def test_sends_typing_on_enter(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, interval=60):
            await asyncio.sleep(0.01)

        client.room_typing.assert_any_call(ROOM, typing_state=True, timeout=30000)

    async def test_sends_typing_false_on_exit(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, interval=60):
            pass

        client.room_typing.assert_any_call(ROOM, typing_state=False)

    async def test_keep_alive_fires_periodically(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, interval=0.05):
            await asyncio.sleep(0.18)

        # enter + at least 2 keep-alive ticks + exit
        true_calls = [
            c for c in client.room_typing.call_args_list if c.kwargs.get("typing_state") is True
        ]
        assert len(true_calls) >= 3

    async def test_task_cancelled_on_exit(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        ctx = MatrixTypingContext(client, ROOM)
        async with ctx:
            assert ctx._task is not None
            assert not ctx._task.done()

        assert ctx._task.done()

    async def test_notify_sends_typing_inline(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, interval=60) as ctx:
            client.room_typing.reset_mock()
            await ctx.notify()

        # notify should have called room_typing(True) immediately
        true_calls = [
            c for c in client.room_typing.call_args_list if c.kwargs.get("typing_state") is True
        ]
        assert len(true_calls) >= 1

    async def test_notify_resets_keep_alive_timer(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, interval=0.1) as ctx:
            # Call notify just before keep-alive would fire
            await asyncio.sleep(0.07)
            client.room_typing.reset_mock()
            await ctx.notify()  # resets timer

            # The keep-alive should NOT fire for another ~0.1s
            await asyncio.sleep(0.05)
            calls_after_notify = client.room_typing.call_args_list

        # Only the notify call, no keep-alive in the 0.05s window
        true_calls = [c for c in calls_after_notify if c.kwargs.get("typing_state") is True]
        assert len(true_calls) == 1

    async def test_error_response_returns_false(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client(success=False)
        ctx = MatrixTypingContext(client, ROOM)
        result = await ctx._send_typing(source="test")

        assert result is False

    async def test_success_response_returns_true(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client(success=True)
        ctx = MatrixTypingContext(client, ROOM)
        result = await ctx._send_typing(source="test")

        assert result is True

    async def test_exception_returns_false(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = MagicMock()
        client.room_typing = AsyncMock(side_effect=RuntimeError("connection lost"))
        ctx = MatrixTypingContext(client, ROOM)
        result = await ctx._send_typing(source="test")

        assert result is False

    async def test_exit_no_error_when_typing_false_fails(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        # Make the typing_state=False call on exit fail
        original = client.room_typing

        async def _side_effect(*args: object, **kwargs: object) -> object:
            if kwargs.get("typing_state") is False:
                raise RuntimeError("gone")
            return await original(*args, **kwargs)

        client.room_typing = AsyncMock(side_effect=_side_effect)
        # Should not raise
        async with MatrixTypingContext(client, ROOM):
            pass

    async def test_custom_timeout(self) -> None:
        from botwerk_bot.matrix.typing import MatrixTypingContext

        client = _make_client()
        async with MatrixTypingContext(client, ROOM, timeout=10000):
            pass

        client.room_typing.assert_any_call(ROOM, typing_state=True, timeout=10000)
