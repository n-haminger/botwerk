"""Tests for the memory agent (triage + write prompt parsing)."""

from __future__ import annotations

import json

from botwerk_bot.cli.types import AgentResponse
from botwerk_bot.memory.agent import MemoryAgent, _format_conversation
from botwerk_bot.memory.conversation_log import LogEntry


def _entry(role: str, text: str) -> LogEntry:
    return LogEntry(role=role, text=text, char_count=len(text), timestamp=0.0)


class TestFormatConversation:
    def test_basic_formatting(self) -> None:
        entries = [_entry("user", "hello"), _entry("assistant", "hi")]
        result = _format_conversation(entries)
        assert "[user]: hello" in result
        assert "[assistant]: hi" in result

    def test_truncation(self) -> None:
        entries = [_entry("user", "x" * 3000)]
        result = _format_conversation(entries)
        assert result.endswith("…")
        assert len(result) < 3000

    def test_compaction_entry(self) -> None:
        entries = [_entry("compaction", "Context compacted (50000 tokens)")]
        result = _format_conversation(entries)
        assert "[SYSTEM:" in result


class TestTriageParsing:
    def test_valid_json(self) -> None:
        response = AgentResponse(
            result=json.dumps({"relevant": True, "summary": "User likes Python"}),
            cost_usd=0.001,
        )
        result = MemoryAgent._parse_triage(response)
        assert result.relevant is True
        assert result.summary == "User likes Python"
        assert result.cost_usd == 0.001

    def test_not_relevant(self) -> None:
        response = AgentResponse(
            result=json.dumps({"relevant": False, "summary": ""}),
        )
        result = MemoryAgent._parse_triage(response)
        assert result.relevant is False

    def test_markdown_fences(self) -> None:
        response = AgentResponse(
            result='```json\n{"relevant": true, "summary": "test"}\n```',
        )
        result = MemoryAgent._parse_triage(response)
        assert result.relevant is True

    def test_invalid_json_defaults_to_not_relevant(self) -> None:
        response = AgentResponse(result="not json at all")
        result = MemoryAgent._parse_triage(response)
        assert result.relevant is False
        assert result.summary == ""

    def test_empty_response(self) -> None:
        response = AgentResponse(result="")
        result = MemoryAgent._parse_triage(response)
        assert result.relevant is False


class TestWriteParsing:
    def test_valid_json(self) -> None:
        data = {
            "new_mainmemory": "# Updated Memory\n\nNew content",
            "shared_additions": None,
            "changes": ["Added user preference"],
        }
        response = AgentResponse(result=json.dumps(data), cost_usd=0.01)
        result = MemoryAgent._parse_write(response)
        assert result.new_mainmemory == "# Updated Memory\n\nNew content"
        assert result.shared_additions is None
        assert result.changes == ["Added user preference"]

    def test_with_shared_additions(self) -> None:
        data = {
            "new_mainmemory": "updated",
            "shared_additions": "- Server runs Ubuntu 24.04",
            "changes": ["Added server info"],
        }
        response = AgentResponse(result=json.dumps(data))
        result = MemoryAgent._parse_write(response)
        assert result.shared_additions == "- Server runs Ubuntu 24.04"

    def test_invalid_json_returns_empty(self) -> None:
        response = AgentResponse(result="broken")
        result = MemoryAgent._parse_write(response)
        assert result.new_mainmemory is None
        assert result.shared_additions is None
        assert result.changes == []

    def test_markdown_fences(self) -> None:
        data = {"new_mainmemory": "content", "shared_additions": None, "changes": []}
        response = AgentResponse(result=f"```json\n{json.dumps(data)}\n```")
        result = MemoryAgent._parse_write(response)
        assert result.new_mainmemory == "content"
