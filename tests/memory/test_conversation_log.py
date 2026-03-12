"""Tests for the ConversationLog ring buffer."""

from __future__ import annotations

from botwerk_bot.memory.conversation_log import ConversationLog


class TestConversationLog:
    def test_append_and_length(self) -> None:
        log = ConversationLog()
        log.append("user", "hello")
        log.append("assistant", "hi there")
        assert len(log) == 2

    def test_unprocessed_returns_new_entries(self) -> None:
        log = ConversationLog()
        log.append("user", "first")
        log.append("assistant", "reply")

        entries = log.unprocessed()
        assert len(entries) == 2
        assert entries[0].role == "user"
        assert entries[0].text == "first"
        assert entries[1].role == "assistant"

    def test_unprocessed_advances_cursor(self) -> None:
        log = ConversationLog()
        log.append("user", "a")
        log.append("assistant", "b")
        log.unprocessed()

        # No new entries since last check.
        assert log.unprocessed() == []

        # Add more.
        log.append("user", "c")
        entries = log.unprocessed()
        assert len(entries) == 1
        assert entries[0].text == "c"

    def test_peek_does_not_advance(self) -> None:
        log = ConversationLog()
        log.append("user", "x")
        peeked = log.peek_unprocessed()
        assert len(peeked) == 1

        # Peek again — still there.
        assert len(log.peek_unprocessed()) == 1

        # unprocessed consumes them.
        consumed = log.unprocessed()
        assert len(consumed) == 1
        assert log.peek_unprocessed() == []

    def test_messages_since_check(self) -> None:
        log = ConversationLog()
        assert log.messages_since_check() == 0

        log.append("user", "a")
        log.append("user", "b")
        assert log.messages_since_check() == 2

        log.unprocessed()
        assert log.messages_since_check() == 0

    def test_chars_since_check(self) -> None:
        log = ConversationLog()
        log.append("user", "hello")  # 5 chars
        log.append("user", "world!!")  # 7 chars
        assert log.chars_since_check() == 12

    def test_mark_compaction(self) -> None:
        log = ConversationLog()
        log.append("user", "msg")
        log.mark_compaction(50000)

        assert log.has_compaction_since_check()
        entries = log.unprocessed()
        assert any(e.role == "compaction" for e in entries)

    def test_compaction_false_after_consume(self) -> None:
        log = ConversationLog()
        log.mark_compaction(1000)
        log.unprocessed()
        assert not log.has_compaction_since_check()

    def test_clear(self) -> None:
        log = ConversationLog()
        log.append("user", "a")
        log.append("user", "b")
        log.mark_compaction(1000)
        log.clear()

        assert len(log) == 0
        assert log.messages_since_check() == 0
        assert not log.has_compaction_since_check()

    def test_ring_buffer_max_entries(self) -> None:
        log = ConversationLog(max_entries=3)
        for i in range(5):
            log.append("user", f"msg-{i}")

        assert len(log) == 3
        entries = log.unprocessed()
        # Only the last 3 survive.
        assert [e.text for e in entries] == ["msg-2", "msg-3", "msg-4"]

    def test_cursor_after_eviction(self) -> None:
        """Cursor is clamped so entries are not lost after deque eviction."""
        log = ConversationLog(max_entries=3)
        log.append("user", "a")
        log.append("user", "b")
        log.unprocessed()  # cursor=2
        log.append("user", "c")
        log.append("user", "d")
        log.append("user", "e")  # evicts "a" and "b", deque has c/d/e
        entries = log.unprocessed()
        # Must return at least the new entries after eviction.
        assert len(entries) > 0
        texts = [e.text for e in entries]
        assert "e" in texts

    def test_metrics_after_eviction(self) -> None:
        log = ConversationLog(max_entries=3)
        log.append("user", "a")
        log.append("user", "b")
        log.unprocessed()  # cursor=2
        # Fill past capacity.
        log.append("user", "c")
        log.append("user", "d")
        log.append("user", "e")
        assert log.messages_since_check() > 0
        assert log.chars_since_check() > 0

    def test_all_unprocessed_same_as_unprocessed(self) -> None:
        log = ConversationLog()
        log.append("user", "a")
        log.append("assistant", "b")
        entries = log.all_unprocessed()
        assert len(entries) == 2
        # Cursor advanced.
        assert log.messages_since_check() == 0
