"""Shared HTTP helpers for task tool scripts."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def detect_agent_name() -> str:
    """Detect the agent name from script path or env var.

    Sub-agent tools live at ``~/.botwerk/agents/<name>/workspace/tools/task_tools/``.
    Main agent tools live at ``~/.botwerk/workspace/tools/task_tools/``.
    The path is the most reliable source — env var is used as fallback.
    """
    # Derive from script path: .../agents/<name>/workspace/tools/task_tools/
    # Avoid .resolve() — it follows symlinks which could point to _home_defaults.
    script_dir = Path(os.path.abspath(__file__)).parent
    # Walk up: task_tools -> tools -> workspace -> <agent_home>
    workspace = script_dir.parent.parent
    if workspace.name == "workspace":
        agent_home = workspace.parent
        if agent_home.parent.name == "agents":
            return agent_home.name
    # Fallback to env var
    return os.environ.get("BOTWERK_AGENT_NAME", "main")


def get_api_url(path: str) -> str:
    """Build internal API URL from environment."""
    port = os.environ.get("BOTWERK_INTERAGENT_PORT", "8799")
    host = os.environ.get("BOTWERK_INTERAGENT_HOST", "127.0.0.1")
    return f"http://{host}:{port}{path}"


def _auth_headers() -> dict[str, str]:
    """Build HTTP headers including auth token if available."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = os.environ.get("BOTWERK_AGENT_SECRET", "")
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def post_json(url: str, body: dict[str, object], *, timeout: int = 300) -> dict[str, object]:
    """POST JSON to internal API, return parsed response."""
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_auth_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.URLError as e:
        print(f"Error: Cannot reach task API at {url}: {e}", file=sys.stderr)
        print("Make sure the Botwerk bot is running with tasks enabled.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def get_json(url: str, *, timeout: int = 10) -> dict[str, object]:
    """GET JSON from internal API, return parsed response."""
    req = urllib.request.Request(url, headers=_auth_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.URLError as e:
        print(f"Error: Cannot reach task API at {url}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
