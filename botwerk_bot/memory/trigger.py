"""Score-based trigger logic for the memory observer.

Instead of a simple "every N messages" counter, the trigger combines message
count and character volume into a weighted score.  A check fires when the
score reaches 1.0.
"""

from __future__ import annotations

from botwerk_bot.memory.conversation_log import ConversationLog


class TriggerState:
    """Evaluates whether a memory check should fire for a given conversation log."""

    def __init__(
        self,
        *,
        message_weight: int = 5,
        char_weight: int = 3000,
    ) -> None:
        self._message_weight = max(message_weight, 1)
        self._char_weight = max(char_weight, 1)

    def score(self, log: ConversationLog) -> float:
        """Compute the trigger score (>= 1.0 means check should fire)."""
        msg_score = log.messages_since_check() / self._message_weight
        char_score = log.chars_since_check() / self._char_weight
        return msg_score + char_score

    def should_check(self, log: ConversationLog) -> bool:
        """Return True when the score threshold is reached."""
        return self.score(log) >= 1.0

    def should_check_immediate(self, log: ConversationLog) -> bool:
        """Return True for high-priority triggers (compaction events)."""
        return log.has_compaction_since_check()
