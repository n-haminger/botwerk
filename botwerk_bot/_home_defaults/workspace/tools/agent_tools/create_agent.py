#!/usr/bin/env python3
"""Create a new sub-agent by writing to agents.json.

The AgentSupervisor watches agents.json via FileWatcher and automatically
starts the new agent within seconds.

Usage:
    python3 create_agent.py --name NAME [--provider P] [--model M]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _agents_path() -> Path:
    """Resolve agents.json path (always in main agent home).

    Sub-agents have BOTWERK_HOME = ~/.botwerk/agents/<name>/, so we navigate
    up to the main home. Main agent's BOTWERK_HOME points directly to ~/.botwerk/.
    """
    import os

    home = Path(os.environ.get("BOTWERK_HOME", str(Path.home() / ".botwerk")))
    direct = home / "agents.json"
    if direct.is_file():
        return direct
    # Sub-agent: navigate up from agents/<name>/ to main home
    main_home = home.parent.parent
    main_path = main_home / "agents.json"
    if main_path.is_file() or (main_home / "config").is_dir():
        return main_path
    return direct


_CLAUDE_MODELS = ("haiku", "sonnet", "opus")


def _main_home() -> Path:
    """Resolve the main agent's BOTWERK_HOME."""
    import os

    home = Path(os.environ.get("BOTWERK_HOME", str(Path.home() / ".botwerk")))
    if home.name != ".botwerk" and (home.parent.parent / "config").is_dir():
        return home.parent.parent
    return home


def _resolve_codex_model(model: str, home: Path) -> str:
    """Validate/resolve a Codex model against the cached model list."""
    cache_path = home / "config" / "codex_models.json"
    if not cache_path.is_file():
        return model
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        models = data.get("models", [])
        valid_ids = [m["id"] for m in models if isinstance(m, dict)]
        if model in valid_ids:
            return model
        for m in models:
            if isinstance(m, dict) and m.get("is_default"):
                print(f"Note: '{model}' is not a valid Codex model. Using default: {m['id']}")
                return m["id"]
        if valid_ids:
            print(f"Note: '{model}' is not a valid Codex model. Using: {valid_ids[0]}")
            return valid_ids[0]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return model


def _resolve_gemini_model(model: str, home: Path) -> str:
    """Validate/resolve a Gemini model against the cached model list."""
    cache_path = home / "config" / "gemini_models.json"
    if not cache_path.is_file():
        return model
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        valid_ids = data.get("models", [])
        if model in valid_ids:
            return model
        if valid_ids:
            print(f"Note: '{model}' is not a valid Gemini model. Using: {valid_ids[0]}")
            return valid_ids[0]
    except (json.JSONDecodeError, OSError):
        pass
    return model


def _resolve_model(provider: str | None, model: str | None) -> str | None:
    """Validate model name against known models for the given provider."""
    if model is None or provider is None:
        return model

    home = _main_home()

    if provider == "claude":
        if model in _CLAUDE_MODELS:
            return model
        print(f"Note: '{model}' is not a valid Claude model. Using: sonnet")
        return "sonnet"

    if provider in ("openai", "codex"):
        return _resolve_codex_model(model, home)

    if provider == "gemini":
        return _resolve_gemini_model(model, home)

    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new sub-agent")
    parser.add_argument("--name", required=True, help="Agent name (lowercase, no spaces)")
    parser.add_argument("--provider", default=None, help="AI provider (claude/openai/gemini)")
    parser.add_argument(
        "--model",
        default=None,
        help="Specific model name (e.g. gpt-5.3-codex, opus, gemini-2.5-pro)",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Short agent description for the join notification (purpose, key commands)",
    )
    parser.add_argument(
        "--linux-user",
        action="store_true",
        default=False,
        help="Run CLI subprocesses as a dedicated Linux user (botwerk-<name>) for isolation",
    )
    args = parser.parse_args()

    # --- Validate name ---
    name = args.name.lower().strip()
    if not name or " " in name or name == "main":
        print(
            f"Error: Invalid agent name '{name}'. Must be lowercase, no spaces, not 'main'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Load existing agents ---
    path = _agents_path()
    agents: list[dict] = []
    if path.is_file():
        try:
            agents = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            agents = []

    # Check for duplicate
    if any(a.get("name") == name for a in agents):
        print(f"Error: Agent '{name}' already exists.", file=sys.stderr)
        sys.exit(1)

    # Normalize provider name (codex -> openai)
    provider = args.provider
    if provider == "codex":
        provider = "openai"

    # Resolve model against cached model lists
    resolved_model = _resolve_model(provider, args.model)

    # --- Build agent entry ---
    entry: dict = {
        "name": name,
    }

    if provider:
        entry["provider"] = provider
    if resolved_model:
        entry["model"] = resolved_model
    if args.linux_user:
        entry["linux_user"] = True

    agents.append(entry)

    # Write
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agents, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Write JOIN_NOTIFICATION.md if description provided
    if args.description:
        agent_workspace = _main_home() / "agents" / name / "workspace"
        agent_workspace.mkdir(parents=True, exist_ok=True)
        notification_path = agent_workspace / "JOIN_NOTIFICATION.md"
        notification_path.write_text(args.description + "\n", encoding="utf-8")
        print(f"  JOIN_NOTIFICATION.md written.")

    # --- Output ---
    print(f"Agent '{name}' created successfully.")
    if provider:
        print(f"  Provider: {provider}")
    if resolved_model:
        print(f"  Model: {resolved_model}")
    if args.linux_user:
        print(f"  Linux user isolation: enabled (botwerk-{name})")
    print(f"\nThe agent starts automatically within a few seconds.")
    print(f"The user can open the sub-agent's chat to talk to it directly.")


if __name__ == "__main__":
    main()
