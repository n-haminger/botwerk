"""Central path resolution for the workspace layout.

This module is the SINGLE SOURCE OF TRUTH for all paths in the framework.
Every path the framework needs is either a field or property of ``BotwerkPaths``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# botwerk_bot/workspace/paths.py -> botwerk_bot/workspace -> botwerk_bot
_PKG_DIR = Path(__file__).resolve().parent.parent


def _default_home_defaults() -> Path:
    return _PKG_DIR / "_home_defaults"


def _default_framework_root() -> Path:
    return _PKG_DIR.parent


@dataclass(frozen=True)
class BotwerkPaths:
    """Resolved, immutable paths for the workspace layout.

    All framework paths are derived from three roots:

    - ``botwerk_home``:    User data directory (default ``~/.botwerk``).
    - ``home_defaults``:  Bundled template that mirrors ``botwerk_home`` (package-internal).
    - ``framework_root``: Repository root (for config.example.json).
    """

    botwerk_home: Path
    home_defaults: Path = field(default_factory=_default_home_defaults)
    framework_root: Path = field(default_factory=_default_framework_root)

    # -- User data paths (inside botwerk_home) --

    @property
    def workspace(self) -> Path:
        return self.botwerk_home / "workspace"

    @property
    def config_dir(self) -> Path:
        return self.botwerk_home / "config"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def sessions_path(self) -> Path:
        return self.botwerk_home / "sessions.json"

    @property
    def cron_jobs_path(self) -> Path:
        return self.botwerk_home / "cron_jobs.json"

    @property
    def webhooks_path(self) -> Path:
        return self.botwerk_home / "webhooks.json"

    @property
    def logs_dir(self) -> Path:
        return self.botwerk_home / "logs"

    @property
    def cron_tasks_dir(self) -> Path:
        return self.workspace / "cron_tasks"

    @property
    def tools_dir(self) -> Path:
        return self.workspace / "tools"

    @property
    def user_tools_dir(self) -> Path:
        return self.workspace / "tools" / "user_tools"

    @property
    def output_to_user_dir(self) -> Path:
        return self.workspace / "output_to_user"

    @property
    def media_files_dir(self) -> Path:
        return self.workspace / "media_files"

    @property
    def api_files_dir(self) -> Path:
        return self.workspace / "api_files"

    @property
    def memory_system_dir(self) -> Path:
        return self.workspace / "memory_system"

    @property
    def skills_dir(self) -> Path:
        return self.workspace / "skills"

    @property
    def bundled_skills_dir(self) -> Path:
        """Package-internal skill directory (read-only, ships with botwerk)."""
        return self.home_defaults / "workspace" / "skills"

    @property
    def tasks_dir(self) -> Path:
        """Per-task metadata folders (TASKMEMORY.md etc.)."""
        return self.workspace / "tasks"

    @property
    def tasks_registry_path(self) -> Path:
        """Task registry persistence."""
        return self.botwerk_home / "tasks.json"

    @property
    def chat_activity_path(self) -> Path:
        return self.botwerk_home / "chat_activity.json"

    @property
    def named_sessions_path(self) -> Path:
        return self.botwerk_home / "named_sessions.json"

    @property
    def startup_state_path(self) -> Path:
        return self.botwerk_home / "startup_state.json"

    @property
    def inflight_turns_path(self) -> Path:
        return self.botwerk_home / "inflight_turns.json"

    @property
    def env_file(self) -> Path:
        """User-managed ``.env`` for external API secrets."""
        return self.botwerk_home / ".env"

    @property
    def mainmemory_path(self) -> Path:
        return self.memory_system_dir / "MAINMEMORY.md"

    @property
    def join_notification_path(self) -> Path:
        return self.workspace / "JOIN_NOTIFICATION.md"

    # -- Framework paths (bundled with package or repo root) --

    @property
    def config_example_path(self) -> Path:
        """Config example: repo root (dev) or package-bundled (installed)."""
        repo_path = self.framework_root / "config.example.json"
        if repo_path.is_file():
            return repo_path
        return _PKG_DIR / "_config_example.json"


def resolve_paths(
    botwerk_home: str | Path | None = None,
    *,
    framework_root: str | Path | None = None,
    home_defaults: str | Path | None = None,
) -> BotwerkPaths:
    """Build BotwerkPaths from explicit values, env vars, or defaults.

    Args:
        botwerk_home: User data directory. Falls back to ``$BOTWERK_HOME`` or ``~/.botwerk``.
        framework_root: Repository root. Falls back to ``$BOTWERK_FRAMEWORK_ROOT``.
        home_defaults: Template directory. Falls back to ``botwerk_bot/_home_defaults/``.
    """
    if botwerk_home is not None:
        home = Path(botwerk_home).expanduser().resolve()
    else:
        home = (
            Path(
                os.environ.get("BOTWERK_HOME", str(Path.home() / ".botwerk")),
            )
            .expanduser()
            .resolve()
        )

    if framework_root is not None:
        fw = Path(framework_root).expanduser().resolve()
    else:
        env_fw = os.environ.get("BOTWERK_FRAMEWORK_ROOT")
        fw = Path(env_fw).resolve() if env_fw else _default_framework_root()

    hd = Path(home_defaults).resolve() if home_defaults is not None else _default_home_defaults()

    return BotwerkPaths(botwerk_home=home, home_defaults=hd, framework_root=fw)
