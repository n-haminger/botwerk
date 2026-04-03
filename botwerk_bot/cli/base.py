"""Base types and abstract interface for CLI backends."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from botwerk_bot.cli.stream_events import StreamEvent
from botwerk_bot.cli.types import CLIResponse

if TYPE_CHECKING:
    from botwerk_bot.cli.process_registry import ProcessRegistry
    from botwerk_bot.cli.timeout_controller import TimeoutController

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"


def _win_feed_stdin(process: asyncio.subprocess.Process, data: str) -> None:
    """Write prompt to stdin and close on Windows; no-op on POSIX."""
    if _IS_WINDOWS and process.stdin is not None:
        process.stdin.write(data.encode())
        process.stdin.close()


async def _feed_stdin_and_close(
    process: asyncio.subprocess.Process,
    data: str,
    *,
    windows_only: bool = False,
) -> None:
    """Write prompt to stdin and close the writer gracefully."""
    if windows_only and not _IS_WINDOWS:
        return

    writer = process.stdin
    if writer is None:
        return

    with contextlib.suppress(BrokenPipeError, ConnectionResetError, RuntimeError, ValueError):
        writer.write(data.encode())
        drain_result = writer.drain()
        if inspect.isawaitable(drain_result):
            await drain_result

    writer.close()
    wait_closed = getattr(writer, "wait_closed", None)
    if wait_closed is None:
        return
    with contextlib.suppress(
        BrokenPipeError,
        ConnectionResetError,
        RuntimeError,
        OSError,
        ValueError,
    ):
        closed_result = wait_closed()
        if inspect.isawaitable(closed_result):
            await closed_result


@dataclass(slots=True)
class CLIConfig:
    """Configuration for any CLI wrapper."""

    provider: str = "claude"
    working_dir: str | Path = "."
    model: str | None = None
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "bypassPermissions"
    # Codex-specific fields (ignored by Claude provider):
    sandbox_mode: str = "read-only"
    images: list[str] = field(default_factory=list)
    instructions: str | None = None
    reasoning_effort: str = "medium"
    # Process tracking (shared across providers):
    process_registry: ProcessRegistry | None = None
    chat_id: int = 0
    topic_id: int | None = None
    process_label: str = "main"
    # Gemini-specific auth fallback:
    gemini_api_key: str | None = None
    # Extra CLI parameters (provider-specific):
    cli_parameters: list[str] = field(default_factory=list)
    # Multi-agent identification:
    agent_name: str = "main"
    interagent_port: int = 8799
    agent_secret: str = ""
    # Linux user isolation:
    linux_user: str = ""


# ---------------------------------------------------------------------------
# sudo wrapping (Linux user isolation)
# ---------------------------------------------------------------------------

# Environment variables preserved through sudo for CLI subprocesses.
_SUDO_PRESERVE_VARS = (
    "BOTWERK_HOME",
    "BOTWERK_AGENT_NAME",
    "BOTWERK_AGENT_ROLE",
    "BOTWERK_AGENT_SECRET",
    "BOTWERK_INTERAGENT_PORT",
    "BOTWERK_CHAT_ID",
    "BOTWERK_TOPIC_ID",
    "BOTWERK_SHARED_MEMORY_PATH",
    "PATH",
    "HOME",
    "NODE_PATH",
    "NVM_DIR",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "PPLX_API_KEY",
    "DEEPSEEK_API_KEY",
)


def sudo_wrap(
    cmd: list[str],
    config: CLIConfig,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], str | None]:
    """Wrap a CLI command for execution as a different Linux user via sudo.

    When ``config.linux_user`` is set, the command
    is prefixed with ``sudo -nu <user> --preserve-env=... --``.

    Returns ``(wrapped_cmd, resolved_cwd)``.
    """
    if not config.linux_user:
        return cmd, str(Path(config.working_dir).resolve())

    logger.debug("sudo_wrap user=%s", config.linux_user)

    # HOME must NOT be preserved — sudo -nu sets it to the target user's
    # home directory, which is where Claude looks for ~/.claude/ credentials.
    preserve_keys = [k for k in _SUDO_PRESERVE_VARS if k != "HOME"]
    if extra_env:
        preserve_keys.extend(k for k in extra_env.keys() if k != "HOME")
    # Load user secrets so their keys are also preserved
    working_dir = Path(config.working_dir)
    botwerk_home = working_dir.parent if working_dir.name == "workspace" else working_dir
    main_home = botwerk_home
    if main_home.parent.name == "agents":
        main_home = main_home.parent.parent

    from botwerk_bot.infra.env_secrets import load_env_secrets

    for key in load_env_secrets(main_home / ".env"):
        if key not in preserve_keys:
            preserve_keys.append(key)

    preserve_csv = ",".join(preserve_keys)
    resolved_cwd = str(Path(config.working_dir).resolve())

    # Resolve the CLI binary to its global path if available.
    # The sudoers entry references the global path (/usr/local/bin/claude),
    # but the command may contain the per-user path (~/.local/bin/claude).
    resolved_cmd = list(cmd)
    if resolved_cmd:
        binary = Path(resolved_cmd[0])
        global_path = Path("/usr/local/bin") / binary.name
        if global_path.exists() and binary != global_path:
            resolved_cmd[0] = str(global_path)

    wrapped = [
        "sudo",
        "-Hnu",
        config.linux_user,
        f"--preserve-env={preserve_csv}",
        "--",
        *resolved_cmd,
    ]
    return wrapped, resolved_cwd


def wrap_command(
    cmd: list[str],
    config: CLIConfig,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], str | None]:
    """Dispatch to ``sudo_wrap`` when Linux user isolation is configured."""
    if config.linux_user:
        return sudo_wrap(cmd, config, extra_env=extra_env)
    return cmd, str(Path(config.working_dir).resolve())


class BaseCLI(ABC):
    """Abstract interface for CLI backends (Claude, Codex, etc.)."""

    @abstractmethod
    async def send(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
    ) -> CLIResponse: ...

    @abstractmethod
    def send_streaming(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
    ) -> AsyncGenerator[StreamEvent, None]: ...
