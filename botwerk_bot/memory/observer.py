"""MemoryObserver: autonomous background observer for memory management.

Runs as a ``BaseObserver`` asyncio task.  Watches conversation logs, decides
when to check for memory-worthy content, and triggers the two-phase
:class:`MemoryAgent` pipeline (triage → write/compact).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from botwerk_bot.infra.base_observer import BaseObserver
from botwerk_bot.memory.agent import MemoryAgent
from botwerk_bot.memory.conversation_log import ConversationLog
from botwerk_bot.memory.trigger import TriggerState

if TYPE_CHECKING:
    from botwerk_bot.cli.service import CLIService

logger = logging.getLogger(__name__)

_POLL_SECONDS = 5


class MemoryObserver(BaseObserver):
    """Autonomous memory manager running in the background.

    Lifecycle:
    1. Conversation flows call :meth:`get_log` to obtain a per-chat
       :class:`ConversationLog` and append user/assistant turns.
    2. The observer's ``_run`` loop polls all logs and evaluates the
       score-based trigger.
    3. When a check fires, :class:`MemoryAgent` runs triage (cheap model);
       if relevant, a write/compact call (strong model) follows.
    4. MAINMEMORY.md (and optionally SHAREDMEMORY.md) are updated on disk.
    """

    def __init__(
        self,
        *,
        mainmemory_path: Path,
        shared_memory_path: Path | None,
        cli_service: CLIService,
        triage_model: str = "haiku",
        triage_provider: str = "claude",
        write_model: str = "sonnet",
        write_provider: str = "claude",
        message_weight: int = 5,
        char_weight: int = 3000,
        idle_check_seconds: int = 300,
        compact_threshold: int = 200,
        check_on_compaction: bool = True,
        check_on_session_end: bool = True,
    ) -> None:
        super().__init__()
        self._mainmemory_path = mainmemory_path
        self._shared_memory_path = shared_memory_path

        self._agent = MemoryAgent(
            cli_service,
            triage_model=triage_model,
            triage_provider=triage_provider,
            write_model=write_model,
            write_provider=write_provider,
            compact_threshold=compact_threshold,
        )
        self._trigger = TriggerState(
            message_weight=message_weight,
            char_weight=char_weight,
        )
        self._idle_check_seconds = idle_check_seconds
        self._check_on_compaction = check_on_compaction
        self._check_on_session_end = check_on_session_end

        # Per-chat conversation logs.
        self._logs: dict[int, ConversationLog] = {}
        # Track last activity per chat for idle detection.
        self._last_activity: dict[int, float] = {}
        # Chats currently being checked (concurrency guard).
        self._checking: set[int] = set()
        # Chats that need an immediate check (e.g. compaction, session end).
        self._immediate_queue: asyncio.Queue[int] = asyncio.Queue()

    # -- Public API -----------------------------------------------------------

    def get_log(self, chat_id: int) -> ConversationLog:
        """Return (or create) the conversation log for *chat_id*."""
        if chat_id not in self._logs:
            self._logs[chat_id] = ConversationLog()
        self._last_activity[chat_id] = time.monotonic()
        return self._logs[chat_id]

    def notify_activity(self, chat_id: int) -> None:
        """Update the last-activity timestamp for idle detection."""
        self._last_activity[chat_id] = time.monotonic()

    def trigger_compaction_check(self, chat_id: int) -> None:
        """Request an immediate memory check after context compaction."""
        if self._check_on_compaction:
            self._immediate_queue.put_nowait(chat_id)

    def notify_session_end(self, chat_id: int) -> None:
        """Final sweep before a session resets."""
        if self._check_on_session_end:
            self._immediate_queue.put_nowait(chat_id)

    # -- Main loop ------------------------------------------------------------

    async def _run(self) -> None:
        """Background loop: poll logs, evaluate triggers, run checks."""
        logger.info("MemoryObserver started")
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("MemoryObserver tick error")
            await asyncio.sleep(_POLL_SECONDS)

    async def _drain_immediate_queue(self) -> None:
        """Process all items queued for immediate checking."""
        while True:
            try:
                chat_id = self._immediate_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if chat_id in self._checking:
                continue
            log = self._logs.get(chat_id)
            if log and log.messages_since_check() > 0:
                await self._guarded_check(chat_id, log, reason="immediate")

    async def _tick(self) -> None:
        """Single poll iteration."""
        await self._drain_immediate_queue()

        # Evaluate score-based triggers for all chats.
        now = time.monotonic()
        for chat_id, log in list(self._logs.items()):
            if chat_id in self._checking or log.messages_since_check() == 0:
                continue
            reason = self._evaluate_trigger(chat_id, now, log)
            if reason:
                await self._guarded_check(chat_id, log, reason=reason)

        # Evict stale chat logs to prevent unbounded memory growth.
        self._evict_stale_logs(now)

    _STALE_SECONDS = 7200  # Evict logs idle for >2 hours with no pending entries.

    def _evict_stale_logs(self, now: float) -> None:
        """Remove conversation logs for chats that have been idle for a long time."""
        stale = [
            cid
            for cid, t in self._last_activity.items()
            if (now - t) > self._STALE_SECONDS
            and cid in self._logs
            and self._logs[cid].messages_since_check() == 0
            and cid not in self._checking
        ]
        for cid in stale:
            del self._logs[cid]
            del self._last_activity[cid]
        if stale:
            logger.debug("Evicted %d stale conversation logs", len(stale))

    def _evaluate_trigger(self, chat_id: int, now: float, log: ConversationLog) -> str:
        """Return trigger reason or empty string if no check needed."""
        if self._trigger.should_check(log):
            return "score"
        if self._idle_check_seconds > 0:
            last = self._last_activity.get(chat_id, now)
            if (now - last) >= self._idle_check_seconds:
                return "idle"
        return ""

    async def _guarded_check(
        self, chat_id: int, log: ConversationLog, *, reason: str
    ) -> None:
        """Run a check with concurrency guard."""
        self._checking.add(chat_id)
        try:
            await self._run_check(chat_id, log, reason=reason)
        finally:
            self._checking.discard(chat_id)

    # -- Check pipeline -------------------------------------------------------

    async def _run_check(self, chat_id: int, log: ConversationLog, *, reason: str) -> None:
        """Execute the triage → write pipeline for one chat."""
        entries = log.unprocessed()
        if not entries:
            return

        mainmemory = self._read_mainmemory()
        logger.info(
            "Memory check chat=%d reason=%s entries=%d chars=%d",
            chat_id,
            reason,
            len(entries),
            sum(e.char_count for e in entries),
        )

        # Phase 1: Triage.
        triage = await self._agent.triage(entries, mainmemory)
        logger.info(
            "Memory triage chat=%d relevant=%s cost=%.4f summary=%s",
            chat_id,
            triage.relevant,
            triage.cost_usd,
            triage.summary[:80] if triage.summary else "",
        )
        if not triage.relevant:
            return

        # Phase 2: Write / compact.
        result = await self._agent.write(entries, mainmemory, triage.summary)
        logger.info(
            "Memory write chat=%d changes=%s cost=%.4f",
            chat_id,
            result.changes,
            result.cost_usd,
        )

        if result.new_mainmemory:
            self._write_mainmemory(result.new_mainmemory)
            logger.info("MAINMEMORY.md updated (%d chars)", len(result.new_mainmemory))

        if result.shared_additions and self._shared_memory_path:
            self._append_shared_memory(result.shared_additions)
            logger.info("SHAREDMEMORY.md appended")

    # -- File I/O -------------------------------------------------------------

    def _read_mainmemory(self) -> str:
        """Read MAINMEMORY.md from disk."""
        try:
            return self._mainmemory_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _write_mainmemory(self, content: str) -> None:
        """Write MAINMEMORY.md atomically."""
        self._mainmemory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._mainmemory_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self._mainmemory_path)

    def _append_shared_memory(self, additions: str) -> None:
        """Append new lines to SHAREDMEMORY.md."""
        if not self._shared_memory_path:
            return
        self._shared_memory_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        with contextlib.suppress(FileNotFoundError):
            existing = self._shared_memory_path.read_text(encoding="utf-8")
        # Append after existing content, before a trailing newline.
        updated = existing.rstrip("\n") + "\n" + additions.strip() + "\n"
        tmp = self._shared_memory_path.with_suffix(".tmp")
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(self._shared_memory_path)
