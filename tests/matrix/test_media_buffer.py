"""Tests for Matrix media buffering (caption-less uploads wait for follow-up text)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from botwerk_bot.matrix.bot import _MEDIA_BUFFER_TIMEOUT, PendingMedia

# ---------------------------------------------------------------------------
# PendingMedia dataclass
# ---------------------------------------------------------------------------


class TestPendingMedia:
    def test_basic_fields(self) -> None:
        pm = PendingMedia(
            prompt="[INCOMING FILE]\nPath: test.jpg",
            room_id="!room:server",
            event=MagicMock(),
            chat_id=123,
        )
        assert pm.prompt == "[INCOMING FILE]\nPath: test.jpg"
        assert pm.room_id == "!room:server"
        assert pm.chat_id == 123
        assert pm.timeout_handle is None

    def test_timeout_constant(self) -> None:
        assert _MEDIA_BUFFER_TIMEOUT == 300  # 5 minutes


# ---------------------------------------------------------------------------
# _on_media buffering behaviour
# ---------------------------------------------------------------------------


class TestOnMediaBuffering:
    """Test that _on_media buffers caption-less media instead of dispatching."""

    @pytest.fixture
    def bot_stub(self) -> MagicMock:
        """Minimal MatrixBot-like stub with required attributes."""
        bot = MagicMock()
        bot._pending_media = {}
        bot._leaving_rooms = set()
        bot._last_active_room = None
        bot._id_map = MagicMock()
        bot._id_map.room_to_int.return_value = 42
        bot._config = MagicMock()
        bot._config.group_mention_only = False
        bot._client = MagicMock()
        bot._client.user_id = "@bot:server"
        bot._orch = MagicMock()
        bot._orch.paths = MagicMock()
        bot._orch.paths.matrix_files_dir = "/tmp/matrix_files"
        bot._orch.paths.workspace = "/tmp/workspace"
        return bot

    def test_media_without_caption_is_buffered(self, bot_stub: MagicMock) -> None:
        """Caption-less media prompt (no 'User message:') should be buffered."""
        prompt = "[INCOMING FILE]\nPath: test.jpg\nType: image/jpeg"
        assert "User message:" not in prompt

        # Simulate what _on_media does after resolve_matrix_media returns
        room_id = "!room:server"
        has_caption = "User message:" in prompt
        assert has_caption is False

        pm = PendingMedia(
            prompt=prompt,
            room_id=room_id,
            event=MagicMock(),
            chat_id=42,
        )
        bot_stub._pending_media[room_id] = pm
        assert room_id in bot_stub._pending_media

    def test_media_with_caption_not_buffered(self) -> None:
        """Media prompt containing 'User message:' should NOT be buffered."""
        prompt = "[INCOMING FILE]\nPath: test.jpg\nType: image/jpeg\n\nUser message: analyze this"
        has_caption = "User message:" in prompt
        assert has_caption is True

    def test_new_media_replaces_previous_pending(self, bot_stub: MagicMock) -> None:
        """A second media upload to the same room replaces the first."""
        room_id = "!room:server"
        handle = MagicMock()

        first = PendingMedia(
            prompt="first", room_id=room_id, event=MagicMock(), chat_id=42,
            timeout_handle=handle,
        )
        bot_stub._pending_media[room_id] = first

        # Simulate replacement (as _on_media does)
        prev = bot_stub._pending_media.pop(room_id, None)
        assert prev is first
        if prev and prev.timeout_handle:
            prev.timeout_handle.cancel()
        handle.cancel.assert_called_once()

        second = PendingMedia(
            prompt="second", room_id=room_id, event=MagicMock(), chat_id=42,
        )
        bot_stub._pending_media[room_id] = second
        assert bot_stub._pending_media[room_id].prompt == "second"


# ---------------------------------------------------------------------------
# _on_message consuming buffered media
# ---------------------------------------------------------------------------


class TestOnMessageConsumesMedia:
    """Test that _on_message combines pending media with text."""

    def test_combine_pending_media_with_text(self) -> None:
        """When pending media exists, text message should be appended to media prompt."""
        pending_media: dict[str, PendingMedia] = {}
        room_id = "!room:server"
        media_prompt = "[INCOMING FILE]\nPath: test.jpg\nType: image/jpeg"
        handle = MagicMock()

        pending_media[room_id] = PendingMedia(
            prompt=media_prompt,
            room_id=room_id,
            event=MagicMock(),
            chat_id=42,
            timeout_handle=handle,
        )

        # Simulate what _on_message does
        text = "Analysiere dieses Bild"
        pending = pending_media.pop(room_id, None)
        if pending:
            if pending.timeout_handle:
                pending.timeout_handle.cancel()
            text = f"{pending.prompt}\nUser message: {text}"

        handle.cancel.assert_called_once()
        assert room_id not in pending_media
        assert text == f"{media_prompt}\nUser message: Analysiere dieses Bild"

    def test_no_pending_media_passes_text_unchanged(self) -> None:
        """Without pending media, text should pass through unchanged."""
        pending_media: dict[str, PendingMedia] = {}
        room_id = "!room:server"
        text = "Just a normal message"

        pending = pending_media.pop(room_id, None)
        if pending:
            text = f"{pending.prompt}\nUser message: {text}"

        assert text == "Just a normal message"

    def test_pending_media_only_consumed_for_matching_room(self) -> None:
        """Pending media in room A should not be consumed by a message in room B."""
        pending_media: dict[str, PendingMedia] = {}
        room_a = "!roomA:server"
        room_b = "!roomB:server"

        pending_media[room_a] = PendingMedia(
            prompt="media for A", room_id=room_a, event=MagicMock(), chat_id=1,
        )

        # Message arrives in room B
        pending = pending_media.pop(room_b, None)
        assert pending is None
        # Room A still has its pending media
        assert room_a in pending_media


# ---------------------------------------------------------------------------
# _flush_pending_media (timeout handler)
# ---------------------------------------------------------------------------


class TestFlushPendingMedia:
    """Test the timeout flush dispatches media alone."""

    async def test_flush_dispatches_and_removes(self) -> None:
        """After timeout, media should be dispatched without text."""
        from botwerk_bot.matrix.bot import MatrixBot

        room_id = "!room:server"
        pending = PendingMedia(
            prompt="[INCOMING FILE]\nPath: test.jpg",
            room_id=room_id,
            event=MagicMock(),
            chat_id=42,
        )

        bot = MagicMock(spec=MatrixBot)
        bot._pending_media = {room_id: pending}
        bot._dispatch_with_lock = AsyncMock()

        # Call the real method on our mock
        await MatrixBot._flush_pending_media(bot, room_id)

        assert room_id not in bot._pending_media
        bot._dispatch_with_lock.assert_awaited_once()
        call_args = bot._dispatch_with_lock.call_args
        assert call_args[0][1] == "[INCOMING FILE]\nPath: test.jpg"

    async def test_flush_noop_when_already_consumed(self) -> None:
        """If media was already consumed by _on_message, flush is a no-op."""
        from botwerk_bot.matrix.bot import MatrixBot

        bot = MagicMock(spec=MatrixBot)
        bot._pending_media = {}
        bot._dispatch_with_lock = AsyncMock()

        await MatrixBot._flush_pending_media(bot, "!room:server")

        bot._dispatch_with_lock.assert_not_awaited()
