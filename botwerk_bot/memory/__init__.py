"""Autonomous memory observer system.

Watches conversations in the background and independently decides when to
update MAINMEMORY.md (and escalate to SHAREDMEMORY.md).
"""

from botwerk_bot.memory.conversation_log import ConversationLog, LogEntry
from botwerk_bot.memory.observer import MemoryObserver
from botwerk_bot.memory.trigger import TriggerState

__all__ = [
    "ConversationLog",
    "LogEntry",
    "MemoryObserver",
    "TriggerState",
]
