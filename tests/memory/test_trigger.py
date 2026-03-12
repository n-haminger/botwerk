"""Tests for the score-based trigger logic."""

from __future__ import annotations

from botwerk_bot.memory.conversation_log import ConversationLog
from botwerk_bot.memory.trigger import TriggerState


class TestTriggerState:
    def test_score_zero_when_empty(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        assert trigger.score(log) == 0.0
        assert not trigger.should_check(log)

    def test_fires_on_message_count(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        for _ in range(5):
            log.append("user", "x")
        assert trigger.score(log) >= 1.0
        assert trigger.should_check(log)

    def test_fires_on_char_count(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        # Single long message.
        log.append("user", "x" * 3000)
        assert trigger.score(log) >= 1.0
        assert trigger.should_check(log)

    def test_mixed_score(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        # 3 messages x 400 chars = 3/5 + 1200/3000 = 0.6 + 0.4 = 1.0
        for _ in range(3):
            log.append("user", "x" * 400)
        assert trigger.score(log) >= 1.0

    def test_below_threshold(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        log.append("user", "hi")
        log.append("assistant", "hello")
        assert trigger.score(log) < 1.0
        assert not trigger.should_check(log)

    def test_cursor_advance_resets_score(self) -> None:
        trigger = TriggerState(message_weight=5, char_weight=3000)
        log = ConversationLog()
        for _ in range(5):
            log.append("user", "x")
        assert trigger.should_check(log)

        log.unprocessed()  # Advance cursor.
        assert trigger.score(log) == 0.0
        assert not trigger.should_check(log)

    def test_immediate_on_compaction(self) -> None:
        trigger = TriggerState()
        log = ConversationLog()
        log.mark_compaction(50000)
        assert trigger.should_check_immediate(log)

    def test_no_immediate_without_compaction(self) -> None:
        trigger = TriggerState()
        log = ConversationLog()
        log.append("user", "hello")
        assert not trigger.should_check_immediate(log)

    def test_minimum_weight_clamped(self) -> None:
        trigger = TriggerState(message_weight=0, char_weight=0)
        log = ConversationLog()
        log.append("user", "x")
        # Should not crash (division by zero) — weights clamped to 1.
        assert trigger.score(log) >= 1.0
