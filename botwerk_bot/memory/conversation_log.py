"""Ring-buffer conversation log for the memory observer.

Captures user prompts, assistant responses, and system events per chat so
the memory observer can analyze recent conversation without access to the
CLI session internals.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class LogEntry:
    """Single conversation log entry."""

    role: str  # "user" | "assistant" | "tool" | "compaction"
    text: str
    char_count: int
    timestamp: float


class ConversationLog:
    """Per-chat ring buffer that records conversation turns.

    The memory observer reads unprocessed entries via :meth:`unprocessed` and
    advances the cursor.  On session end, :meth:`all_unprocessed` returns
    everything since the last check (for a final sweep).

    The cursor is clamped on every read so that entries evicted by the
    ``maxlen`` deque do not cause silent data loss.
    """

    def __init__(self, max_entries: int = 200) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._cursor: int = 0

    # -- Append helpers -------------------------------------------------------

    def append(self, role: str, text: str) -> None:
        """Append a conversation entry."""
        entry = LogEntry(
            role=role,
            text=text,
            char_count=len(text),
            timestamp=time.monotonic(),
        )
        self._entries.append(entry)

    def mark_compaction(self, pre_tokens: int) -> None:
        """Record that context compaction occurred."""
        self.append("compaction", f"Context compacted ({pre_tokens} tokens)")

    # -- Cursor helpers -------------------------------------------------------

    def _clamped_cursor(self) -> int:
        """Return cursor clamped to valid range after possible eviction."""
        return min(self._cursor, len(self._entries))

    # -- Read helpers ---------------------------------------------------------

    def unprocessed(self) -> list[LogEntry]:
        """Return entries since the last check and advance the cursor."""
        entries = list(self._entries)
        cursor = self._clamped_cursor()
        result = entries[cursor:]
        self._cursor = len(entries)
        return result

    def all_unprocessed(self) -> list[LogEntry]:
        """Return all unprocessed entries (for session-end sweep).

        Same as :meth:`unprocessed` but named for clarity at call sites.
        """
        return self.unprocessed()

    def peek_unprocessed(self) -> list[LogEntry]:
        """Peek at unprocessed entries without advancing the cursor."""
        return list(self._entries)[self._clamped_cursor() :]

    # -- Metrics --------------------------------------------------------------

    def messages_since_check(self) -> int:
        """Count of entries since last cursor advance."""
        return max(0, len(self._entries) - self._clamped_cursor())

    def chars_since_check(self) -> int:
        """Total characters in entries since last cursor advance."""
        return sum(e.char_count for e in list(self._entries)[self._clamped_cursor() :])

    def has_compaction_since_check(self) -> bool:
        """True if a compaction event occurred since last check."""
        entries = list(self._entries)[self._clamped_cursor() :]
        return any(e.role == "compaction" for e in entries)

    def clear(self) -> None:
        """Reset the log (e.g. on session reset)."""
        self._entries.clear()
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._entries)
