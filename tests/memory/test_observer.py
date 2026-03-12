"""Tests for the MemoryObserver."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from botwerk_bot.cli.types import AgentResponse
from botwerk_bot.memory.observer import MemoryObserver


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    mainmemory = tmp_path / "memory_system" / "MAINMEMORY.md"
    mainmemory.parent.mkdir(parents=True)
    mainmemory.write_text("# Main Memory\n\n## User\n- Name: Test\n", encoding="utf-8")

    shared = tmp_path / "SHAREDMEMORY.md"
    shared.write_text("# Shared\n", encoding="utf-8")
    return mainmemory, shared


@pytest.fixture
def mock_cli() -> AsyncMock:
    cli = AsyncMock()
    return cli


@pytest.fixture
def observer(tmp_paths: tuple[Path, Path], mock_cli: AsyncMock) -> MemoryObserver:
    mainmemory, shared = tmp_paths
    return MemoryObserver(
        mainmemory_path=mainmemory,
        shared_memory_path=shared,
        cli_service=mock_cli,
        triage_model="haiku",
        triage_provider="claude",
        write_model="sonnet",
        write_provider="claude",
        message_weight=3,  # Low threshold for tests.
        char_weight=500,
    )


class TestGetLog:
    def test_creates_log_per_chat(self, observer: MemoryObserver) -> None:
        log1 = observer.get_log(111)
        log2 = observer.get_log(222)
        assert log1 is not log2

    def test_returns_same_log_for_same_chat(self, observer: MemoryObserver) -> None:
        log1 = observer.get_log(111)
        log2 = observer.get_log(111)
        assert log1 is log2


class TestTriggerImmediate:
    def test_queues_chat_id(self, observer: MemoryObserver) -> None:
        observer.trigger_compaction_check(42)
        assert not observer._immediate_queue.empty()


class TestNotifySessionEnd:
    def test_queues_chat_id(self, observer: MemoryObserver) -> None:
        observer.notify_session_end(42)
        assert not observer._immediate_queue.empty()


class TestFileIO:
    def test_read_mainmemory(
        self, observer: MemoryObserver, tmp_paths: tuple[Path, Path]
    ) -> None:
        content = observer._read_mainmemory()
        assert "# Main Memory" in content

    def test_read_missing_mainmemory(self, mock_cli: AsyncMock) -> None:
        obs = MemoryObserver(
            mainmemory_path=Path("/nonexistent/MAINMEMORY.md"),
            shared_memory_path=None,
            cli_service=mock_cli,
        )
        assert obs._read_mainmemory() == ""

    def test_write_mainmemory(
        self, observer: MemoryObserver, tmp_paths: tuple[Path, Path]
    ) -> None:
        observer._write_mainmemory("# New Content\n")
        mainmemory, _ = tmp_paths
        assert mainmemory.read_text(encoding="utf-8") == "# New Content\n"

    def test_append_shared_memory(
        self, observer: MemoryObserver, tmp_paths: tuple[Path, Path]
    ) -> None:
        observer._append_shared_memory("- New fact about server")
        _, shared = tmp_paths
        content = shared.read_text(encoding="utf-8")
        assert "- New fact about server" in content
        assert content.startswith("# Shared")


class TestRunCheck:
    @pytest.mark.asyncio
    async def test_triage_not_relevant_skips_write(
        self, observer: MemoryObserver, mock_cli: AsyncMock
    ) -> None:
        mock_cli.execute = AsyncMock(
            return_value=AgentResponse(
                result=json.dumps({"relevant": False, "summary": ""}),
                cost_usd=0.001,
            )
        )
        log = observer.get_log(1)
        log.append("user", "hello")
        log.append("assistant", "hi")

        await observer._run_check(1, log, reason="test")

        # Only triage called, no write.
        assert mock_cli.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_triage_relevant_triggers_write(
        self,
        observer: MemoryObserver,
        mock_cli: AsyncMock,
        tmp_paths: tuple[Path, Path],
    ) -> None:
        triage_response = AgentResponse(
            result=json.dumps({"relevant": True, "summary": "User prefers Python"}),
            cost_usd=0.001,
        )
        write_response = AgentResponse(
            result=json.dumps({
                "new_mainmemory": "# Updated\n\n- Prefers Python\n",
                "shared_additions": None,
                "changes": ["Added Python preference"],
            }),
            cost_usd=0.01,
        )
        mock_cli.execute = AsyncMock(side_effect=[triage_response, write_response])

        log = observer.get_log(1)
        log.append("user", "I love Python")
        log.append("assistant", "Good choice")

        await observer._run_check(1, log, reason="test")

        assert mock_cli.execute.call_count == 2
        mainmemory, _ = tmp_paths
        assert "Prefers Python" in mainmemory.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_shared_escalation(
        self,
        observer: MemoryObserver,
        mock_cli: AsyncMock,
        tmp_paths: tuple[Path, Path],
    ) -> None:
        triage_response = AgentResponse(
            result=json.dumps({"relevant": True, "summary": "Server info"}),
            cost_usd=0.001,
        )
        write_response = AgentResponse(
            result=json.dumps({
                "new_mainmemory": None,
                "shared_additions": "- Server runs Ubuntu 24.04",
                "changes": ["Escalated server info"],
            }),
            cost_usd=0.01,
        )
        mock_cli.execute = AsyncMock(side_effect=[triage_response, write_response])

        log = observer.get_log(1)
        log.append("user", "The server runs Ubuntu 24.04")

        await observer._run_check(1, log, reason="test")

        _, shared = tmp_paths
        assert "Ubuntu 24.04" in shared.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_empty_entries_skipped(
        self, observer: MemoryObserver, mock_cli: AsyncMock
    ) -> None:
        log = observer.get_log(1)
        # No entries — cursor at 0, unprocessed returns [].
        await observer._run_check(1, log, reason="test")
        mock_cli.execute.assert_not_called()


class TestTick:
    @pytest.mark.asyncio
    async def test_immediate_queue_processed(
        self, observer: MemoryObserver, mock_cli: AsyncMock
    ) -> None:
        mock_cli.execute = AsyncMock(
            return_value=AgentResponse(
                result=json.dumps({"relevant": False, "summary": ""}),
                cost_usd=0.001,
            )
        )
        log = observer.get_log(1)
        log.append("user", "important msg")
        observer.trigger_compaction_check(1)

        await observer._tick()
        assert mock_cli.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_score_trigger(
        self, observer: MemoryObserver, mock_cli: AsyncMock
    ) -> None:
        mock_cli.execute = AsyncMock(
            return_value=AgentResponse(
                result=json.dumps({"relevant": False, "summary": ""}),
                cost_usd=0.001,
            )
        )
        log = observer.get_log(1)
        # message_weight=3, so 3 messages should trigger.
        for _ in range(3):
            log.append("user", "message")

        await observer._tick()
        assert mock_cli.execute.call_count == 1
