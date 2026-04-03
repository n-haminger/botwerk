"""``botwerk setup`` command: interactive WebUI setup wizard."""

from __future__ import annotations

import asyncio
import json
import secrets

import questionary
from rich.console import Console
from rich.panel import Panel

from botwerk_bot.workspace.paths import resolve_paths

_console = Console()


def _read_config() -> tuple[object, dict[str, object]] | None:
    """Read and return (config_path, data) or None on failure."""
    paths = resolve_paths()
    config_path = paths.config_path
    if not config_path.exists():
        _console.print("[bold red]Config not found.[/bold red] Run [bold]botwerk[/bold] first.")
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _console.print("[bold red]Failed to read config.[/bold red]")
        return None
    return config_path, data


def cmd_setup() -> None:
    """Interactive WebUI setup: create DB, admin user, configure port, generate secret."""
    from botwerk_bot.infra.json_store import atomic_json_save
    from botwerk_bot.webui.auth import hash_password
    from botwerk_bot.webui.database import init_db
    from botwerk_bot.webui.models import User

    _console.print()
    _console.print(
        Panel(
            "[bold]Botwerk WebUI Setup[/bold]\n\n"
            "This wizard will configure the web interface.",
            border_style="blue",
            padding=(1, 2),
        ),
    )

    # -- Read existing config --------------------------------------------------

    result = _read_config()
    if result is None:
        return
    config_path, data = result

    webui = data.get("webui", {})
    if not isinstance(webui, dict):
        webui = {}

    # -- Port ------------------------------------------------------------------

    current_port = webui.get("port", 8080)
    port_str = questionary.text(
        "WebUI port:",
        default=str(current_port),
        validate=lambda v: v.isdigit() and 1024 <= int(v) <= 65535,
    ).ask()
    if port_str is None:  # Ctrl+C
        _console.print("[dim]Setup cancelled.[/dim]")
        return
    port = int(port_str)

    # -- Host ------------------------------------------------------------------

    host = questionary.text(
        "WebUI host (bind address):",
        default=str(webui.get("host", "127.0.0.1")),
    ).ask()
    if host is None:
        _console.print("[dim]Setup cancelled.[/dim]")
        return

    # -- Behind proxy ----------------------------------------------------------

    behind_proxy = questionary.confirm(
        "Behind a reverse proxy? (trust X-Forwarded-* headers)",
        default=bool(webui.get("behind_proxy", False)),
    ).ask()
    if behind_proxy is None:
        _console.print("[dim]Setup cancelled.[/dim]")
        return

    # -- Secret key ------------------------------------------------------------

    existing_key = webui.get("secret_key", "")
    if existing_key:
        regen = questionary.confirm(
            "Secret key already set. Regenerate?",
            default=False,
        ).ask()
        if regen is None:
            _console.print("[dim]Setup cancelled.[/dim]")
            return
        secret_key = secrets.token_urlsafe(32) if regen else str(existing_key)
    else:
        secret_key = secrets.token_urlsafe(32)

    # -- Write config ----------------------------------------------------------

    webui.update({
        "enabled": True,
        "host": host,
        "port": port,
        "behind_proxy": behind_proxy,
        "secret_key": secret_key,
    })
    data["webui"] = webui
    atomic_json_save(config_path, data)

    # -- Initialize database ---------------------------------------------------

    paths = resolve_paths()
    db_path = str(paths.botwerk_home / "webui.db")

    async def _init() -> None:
        engine = await init_db(db_path)
        await engine.dispose()

    asyncio.run(_init())
    _console.print("[green]Database initialized.[/green]")

    # -- Create admin user -----------------------------------------------------

    create_admin = questionary.confirm(
        "Create an admin user now?",
        default=True,
    ).ask()
    if create_admin is None:
        _console.print("[dim]Setup cancelled.[/dim]")
        return

    if create_admin:
        username = questionary.text(
            "Admin username:",
            default="admin",
            validate=lambda v: len(v) >= 2,
        ).ask()
        if username is None:
            _console.print("[dim]Setup cancelled.[/dim]")
            return

        password = questionary.password(
            "Admin password:",
            validate=lambda v: len(v) >= 8,
        ).ask()
        if password is None:
            _console.print("[dim]Setup cancelled.[/dim]")
            return

        display_name = questionary.text(
            "Display name:",
            default=username,
        ).ask()
        if display_name is None:
            _console.print("[dim]Setup cancelled.[/dim]")
            return

        async def _create_user() -> None:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                user = User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=display_name or username,
                    is_admin=True,
                )
                session.add(user)
                await session.commit()
            await engine.dispose()

        asyncio.run(_create_user())
        _console.print(f"[green]Admin user '{username}' created.[/green]")

    # -- Summary ---------------------------------------------------------------

    _console.print()
    _console.print(
        Panel(
            "[bold green]WebUI setup complete![/bold green]\n\n"
            f"  Host:   [cyan]{host}[/cyan]\n"
            f"  Port:   [cyan]{port}[/cyan]\n"
            f"  Proxy:  [cyan]{behind_proxy}[/cyan]\n"
            f"  DB:     [cyan]{db_path}[/cyan]\n\n"
            "[dim]Restart the bot to start the WebUI server.[/dim]",
            title="[bold]Summary[/bold]",
            border_style="green",
            padding=(1, 2),
        ),
    )
    _console.print()
