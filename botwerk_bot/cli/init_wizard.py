"""Interactive onboarding wizard for first-time setup."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from botwerk_bot.cli.auth import AuthStatus, check_claude_auth, check_codex_auth, check_gemini_auth
from botwerk_bot.config import DEFAULT_EMPTY_GEMINI_API_KEY, AgentConfig, deep_merge_config
from botwerk_bot.workspace.init import init_workspace
from botwerk_bot.workspace.paths import resolve_paths

_BANNER_PATH = Path(__file__).resolve().parent.parent / "_banner.txt"
logger = logging.getLogger(__name__)


def _load_banner() -> str:
    """Read ASCII art from bundled file."""
    try:
        return _BANNER_PATH.read_text(encoding="utf-8").rstrip()
    except OSError:
        return "botwerk"


_TIMEZONES: list[str] = [
    # Europe
    "Europe/Berlin",
    "Europe/London",
    "Europe/Paris",
    "Europe/Zurich",
    "Europe/Moscow",
    "Europe/Amsterdam",
    "Europe/Rome",
    "Europe/Madrid",
    # Americas
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "America/Toronto",
    # Asia & Middle East
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Singapore",
    # Oceania & Other
    "Australia/Sydney",
    "Pacific/Auckland",
    "UTC",
]

_MANUAL_TZ_OPTION = "-> Enter manually"


def _abort() -> NoReturn:
    """Print abort message and exit."""
    Console().print("\n[dim]Setup cancelled.[/dim]\n")
    sys.exit(0)


def _show_banner(console: Console) -> None:
    """Display the ASCII art banner."""
    banner = Text(_load_banner(), style="bold cyan")
    console.print(
        Panel(
            banner,
            subtitle="[dim]botwerk[/dim]",
            border_style="cyan",
            padding=(0, 2),
        ),
    )


_STATUS_ICON = {
    AuthStatus.AUTHENTICATED: "[bold green]authenticated[/bold green]",
    AuthStatus.INSTALLED: "[bold yellow]installed but not logged in[/bold yellow]",
    AuthStatus.NOT_FOUND: "[dim]not found[/dim]",
}


def _check_clis(console: Console) -> None:
    """Detect CLI availability and require at least one authenticated provider."""
    claude = check_claude_auth()
    codex = check_codex_auth()
    gemini = check_gemini_auth()

    lines = [
        "[bold]Detected AI Backends:[/bold]\n",
        f"  Claude Code CLI   {_STATUS_ICON[claude.status]}",
        f"  OpenAI Codex CLI  {_STATUS_ICON[codex.status]}",
        f"  Google Gemini CLI {_STATUS_ICON[gemini.status]}",
    ]

    has_auth = claude.is_authenticated or codex.is_authenticated or gemini.is_authenticated

    if has_auth:
        border = "green"
    else:
        border = "red"
        lines.append(
            "\n[bold red]At least one CLI must be installed and authenticated.[/bold red]\n\n"
            "  Claude: [dim]https://docs.anthropic.com/en/docs/claude-code[/dim]\n"
            "  Codex:  [dim]https://github.com/openai/codex[/dim]\n"
            "  Gemini: [dim]https://github.com/google-gemini/gemini-cli[/dim]"
        )

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]CLI Backends[/bold]",
            border_style=border,
            padding=(1, 2),
        ),
    )

    if not has_auth:
        console.print()
        _abort()


def _show_disclaimer(console: Console) -> None:
    """Display the risk disclaimer and require confirmation."""
    disclaimer = (
        "[bold]Important -- please read before continuing.[/bold]\n\n"
        "botwerk connects to [bold]Anthropic Claude CLI[/bold] and "
        "[bold]OpenAI Codex CLI[/bold] as AI agent backends.\n\n"
        "The bot operates in [bold yellow]full permission bypass mode[/bold yellow]. "
        "The agent can read, write, and delete files, execute commands, "
        "and interact with your system without asking for confirmation.\n\n"
        "While safeguards are in place, [bold red]unintended actions can occur[/bold red] "
        "-- including data loss, unexpected file changes, or unintended command execution."
    )
    console.print(
        Panel(
            disclaimer,
            title="[bold yellow]Disclaimer[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    accepted = questionary.confirm(
        "I understand the risks and want to continue.",
        default=False,
    ).ask()
    if not accepted:
        _abort()


# ---------------------------------------------------------------------------
# Common steps
# ---------------------------------------------------------------------------


def _ask_timezone(console: Console) -> str:
    """Prompt for timezone selection."""
    console.print(
        Panel(
            "Your timezone is used for cron scheduling, heartbeat quiet hours,\n"
            "and daily session resets.",
            title="[bold]Timezone[/bold]",
            border_style="blue",
            padding=(1, 2),
        ),
    )

    choices = [*_TIMEZONES, _MANUAL_TZ_OPTION]
    selected: str | None = questionary.select("Select your timezone:", choices=choices).ask()
    if selected is None:
        _abort()

    if selected != _MANUAL_TZ_OPTION:
        return str(selected)

    while True:
        manual: str | None = questionary.text("Enter IANA timezone (e.g. Europe/Berlin):").ask()
        if manual is None:
            _abort()
        manual = manual.strip()
        try:
            ZoneInfo(manual)
        except (ZoneInfoNotFoundError, KeyError):
            console.print(f"[red]Unknown timezone: {manual}[/red]")
            continue
        return str(manual)


def _offer_service_install(console: Console) -> bool:
    """Ask whether to install botwerk as a background service."""
    from botwerk_bot.infra.service import is_service_available

    if not is_service_available():
        return False

    is_windows = sys.platform == "win32"
    is_macos = sys.platform == "darwin"
    if is_windows:
        mechanism = "scheduled task"
        trigger = "login"
    elif is_macos:
        mechanism = "launch agent"
        trigger = "login"
    else:
        mechanism = "systemd service"
        trigger = "boot"

    console.print(
        Panel(
            f"[bold]Run botwerk as a background service?[/bold]\n\n"
            f"This creates a {mechanism} that:\n\n"
            f"  - Starts botwerk on {trigger}\n"
            "  - Restarts automatically on crash\n"
            "  - Keeps running in the background\n\n"
            "[dim]Recommended for VPS or always-on setups.[/dim]",
            title="[bold]Background Service[/bold]",
            border_style="blue",
            padding=(1, 2),
        ),
    )

    enabled: bool | None = questionary.confirm(
        "Install as background service? (Recommended for VPS)",
        default=True,
    ).ask()
    if enabled is None:
        _abort()
    console.print()
    return bool(enabled)


# ---------------------------------------------------------------------------
# Config writing
# ---------------------------------------------------------------------------


def _write_config(
    *,
    user_timezone: str,
) -> Path:
    """Write the config file with wizard values merged into defaults."""
    paths = resolve_paths()
    config_path = paths.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        try:
            existing: dict[str, object] = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Ignoring invalid config file during onboarding: %s", config_path)
            existing = {}
    else:
        existing = {}

    defaults = AgentConfig().model_dump(mode="json")
    defaults["gemini_api_key"] = DEFAULT_EMPTY_GEMINI_API_KEY
    merged, _ = deep_merge_config(existing, defaults)
    if merged.get("gemini_api_key") is None:
        merged["gemini_api_key"] = DEFAULT_EMPTY_GEMINI_API_KEY

    merged["user_timezone"] = user_timezone

    from botwerk_bot.infra.json_store import atomic_json_save

    atomic_json_save(config_path, merged)

    init_workspace(paths)
    return config_path


# ---------------------------------------------------------------------------
# Onboarding flow
# ---------------------------------------------------------------------------


def run_onboarding() -> bool:
    """Run onboarding and return True only when service install succeeded."""
    console = Console()
    console.print()
    _show_banner(console)

    _check_clis(console)
    console.print()

    _show_disclaimer(console)
    console.print()

    timezone = _ask_timezone(console)
    console.print()

    config_path = _write_config(
        user_timezone=timezone,
    )

    paths = resolve_paths()

    # Offer background service setup on Linux with systemd
    run_as_service = _offer_service_install(console)

    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            "[bold]Your botwerk files:[/bold]\n\n"
            f"  Home:       [cyan]{paths.botwerk_home}[/cyan]\n"
            f"  Config:     [cyan]{config_path}[/cyan]\n"
            f"  Workspace:  [cyan]{paths.workspace}[/cyan]\n"
            f"  Logs:       [cyan]{paths.logs_dir}[/cyan]\n\n"
            + ("Installing service..." if run_as_service else "Starting bot..."),
            title="[bold green]Ready[/bold green]",
            border_style="green",
            padding=(1, 2),
        ),
    )
    console.print()

    service_installed = False
    if run_as_service:
        from botwerk_bot.infra.service import install_service

        service_installed = install_service(console)

    return service_installed


def run_smart_reset(botwerk_home: Path) -> None:
    """Warn user and delete workspace for fresh setup."""
    console = Console()
    console.print()

    # Warning panel
    console.print(
        Panel(
            "[bold yellow]You already have a configured setup.[/bold yellow]\n\n"
            "Re-running onboarding will perform a [bold red]full reset[/bold red]:\n\n"
            f"  [dim]{botwerk_home}[/dim] will be deleted entirely.\n"
            "  All sessions, configs, memory, and cron tasks will be lost.",
            title="[bold yellow]Existing Setup Detected[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ),
    )

    # Final confirmation
    console.print()
    confirmed: bool | None = questionary.confirm(
        "Delete everything and start fresh?",
        default=False,
    ).ask()
    if not confirmed:
        _abort()

    from botwerk_bot.infra.fs import robust_rmtree

    robust_rmtree(botwerk_home)
    if botwerk_home.exists():
        console.print(
            f"[yellow]Warning: Could not fully delete {botwerk_home}. Remove manually.[/yellow]\n"
        )
    else:
        console.print("[dim]Workspace deleted.[/dim]\n")
