"""Memory agent: two-phase LLM calls for triage and write/compact.

Phase 1 (triage): cheap/fast model decides whether new durable facts exist.
Phase 2 (write):  stronger model updates MAINMEMORY.md and optionally
                  escalates cross-agent facts to SHAREDMEMORY.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from botwerk_bot.cli.service import CLIService
from botwerk_bot.cli.types import AgentRequest, AgentResponse
from botwerk_bot.memory.conversation_log import LogEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_TRIAGE_PROMPT = """\
You are a memory triage agent.  Analyze the conversation excerpt below and \
decide whether it contains durable facts worth persisting to long-term memory.

## Current MAINMEMORY.md
{mainmemory}

## Conversation since last check
{conversation}

Respond with JSON only — no markdown fences, no commentary:
{{"relevant": true/false, "summary": "one-line summary of what is new (or empty)"}}

Mark relevant=true ONLY for: user preferences, personal facts, project \
decisions, recurring patterns, identity details, tool/workflow preferences.
Mark relevant=false for: ephemeral debugging, code snippets, one-off tasks, \
greetings, questions already answered.
"""

_WRITE_PROMPT = """\
You are a memory manager for an AI assistant in a multi-agent system.

## Current MAINMEMORY.md
{mainmemory}

## Triage summary
{triage_summary}

## Conversation excerpt
{conversation}

## Your tasks

1. **UPDATE** MAINMEMORY.md with new durable facts from the conversation.
   - Merge duplicates and remove contradicted information.
   - Keep under {compact_threshold} lines.  If over, summarise and deduplicate.
   - Preserve the existing Markdown section structure.
   - Do NOT remove the SHARED KNOWLEDGE block (between the markers).

2. **ESCALATE** to SHAREDMEMORY if any facts apply to ALL agents in the \
multi-agent system (server infrastructure, user identity, cross-agent \
preferences).  Only truly cross-agent facts belong here.

Respond with JSON only — no markdown fences, no commentary:
{{
  "new_mainmemory": "<full updated MAINMEMORY content or null if unchanged>",
  "shared_additions": "<new lines to append to SHAREDMEMORY or null>",
  "changes": ["short description of each change"]
}}
"""


def _format_conversation(entries: list[LogEntry]) -> str:
    """Format log entries into a readable conversation excerpt."""
    lines: list[str] = []
    for entry in entries:
        if entry.role == "compaction":
            lines.append(f"[SYSTEM: {entry.text}]")
        else:
            # Truncate very long entries to keep prompt size manageable.
            text = entry.text[:2000] + "…" if len(entry.text) > 2000 else entry.text
            lines.append(f"[{entry.role}]: {text}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TriageResult:
    """Outcome of phase-1 triage."""

    relevant: bool
    summary: str
    cost_usd: float = 0.0


@dataclass(slots=True)
class WriteResult:
    """Outcome of phase-2 write/compact."""

    new_mainmemory: str | None
    shared_additions: str | None
    changes: list[str]
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Agent calls
# ---------------------------------------------------------------------------


class MemoryAgent:
    """Encapsulates the two-phase LLM calls for memory management."""

    def __init__(
        self,
        cli_service: CLIService,
        *,
        triage_model: str = "haiku",
        triage_provider: str = "claude",
        write_model: str = "sonnet",
        write_provider: str = "claude",
        compact_threshold: int = 200,
    ) -> None:
        self._cli = cli_service
        self._triage_model = triage_model
        self._triage_provider = triage_provider
        self._write_model = write_model
        self._write_provider = write_provider
        self._compact_threshold = compact_threshold

    async def triage(
        self,
        entries: list[LogEntry],
        mainmemory: str,
    ) -> TriageResult:
        """Phase 1: decide whether the conversation contains memory-worthy info."""
        conversation = _format_conversation(entries)
        prompt = _TRIAGE_PROMPT.format(
            mainmemory=mainmemory or "(empty)",
            conversation=conversation,
        )
        response = await self._call(
            prompt,
            model=self._triage_model,
            provider=self._triage_provider,
            label="memory-triage",
        )
        return self._parse_triage(response)

    async def write(
        self,
        entries: list[LogEntry],
        mainmemory: str,
        triage_summary: str,
    ) -> WriteResult:
        """Phase 2: update MAINMEMORY.md and optionally escalate to SHAREDMEMORY."""
        conversation = _format_conversation(entries)
        prompt = _WRITE_PROMPT.format(
            mainmemory=mainmemory or "(empty)",
            triage_summary=triage_summary,
            conversation=conversation,
            compact_threshold=self._compact_threshold,
        )
        response = await self._call(
            prompt,
            model=self._write_model,
            provider=self._write_provider,
            label="memory-write",
        )
        return self._parse_write(response)

    # -- Internals ------------------------------------------------------------

    async def _call(
        self,
        prompt: str,
        *,
        model: str,
        provider: str,
        label: str,
    ) -> AgentResponse:
        """Fire a one-shot CLI call for memory work."""
        request = AgentRequest(
            prompt=prompt,
            model_override=model,
            provider_override=provider,
            process_label=label,
        )
        return await self._cli.execute(request)

    @staticmethod
    def _parse_triage(response: AgentResponse) -> TriageResult:
        """Parse the JSON response from the triage call."""
        text = response.result.strip()
        try:
            # Strip markdown fences if the model added them anyway.
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            return TriageResult(
                relevant=bool(data.get("relevant", False)),
                summary=str(data.get("summary", "")),
                cost_usd=response.cost_usd,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Memory triage parse error, treating as not relevant: %s", text[:200])
            return TriageResult(relevant=False, summary="", cost_usd=response.cost_usd)

    @staticmethod
    def _parse_write(response: AgentResponse) -> WriteResult:
        """Parse the JSON response from the write/compact call."""
        text = response.result.strip()
        try:
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            return WriteResult(
                new_mainmemory=data.get("new_mainmemory"),
                shared_additions=data.get("shared_additions"),
                changes=data.get("changes", []),
                cost_usd=response.cost_usd,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Memory write parse error, skipping update: %s", text[:200])
            return WriteResult(
                new_mainmemory=None,
                shared_additions=None,
                changes=[],
                cost_usd=response.cost_usd,
            )
