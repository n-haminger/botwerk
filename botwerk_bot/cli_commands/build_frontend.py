"""``botwerk build-frontend`` command: build the SvelteKit frontend and deploy it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

_console = Console()

# Default frontend source directory relative to the package root.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


def _find_node() -> str | None:
    """Return the path to the Node.js binary, or None if not found."""
    return shutil.which("node")


def _find_npm() -> str | None:
    """Return the path to the npm binary, or None if not found."""
    return shutil.which("npm")


def cmd_build_frontend(args: list[str] | None = None) -> None:
    """Build the SvelteKit frontend and copy output to the configured frontend_dir.

    Requires Node.js and npm to be installed at build time.
    """
    frontend_src = _FRONTEND_DIR
    if args:
        for i, arg in enumerate(args):
            if arg == "--source" and i + 1 < len(args):
                frontend_src = Path(args[i + 1])

    # -- Validate prerequisites ------------------------------------------------

    if not _find_node():
        _console.print(
            "[bold red]Node.js not found.[/bold red]\n"
            "Install Node.js (v18+) to build the frontend.\n"
            "See https://nodejs.org/"
        )
        sys.exit(1)

    npm_path = _find_npm()
    if not npm_path:
        _console.print("[bold red]npm not found.[/bold red] Install Node.js (v18+).")
        sys.exit(1)

    if not frontend_src.is_dir():
        _console.print(
            f"[bold red]Frontend source directory not found:[/bold red] {frontend_src}\n"
            "Make sure the frontend/ directory exists in the project root."
        )
        sys.exit(1)

    # -- Resolve output directory ----------------------------------------------

    output_dir: Path | None = None
    if args:
        for i, arg in enumerate(args):
            if arg == "--output" and i + 1 < len(args):
                output_dir = Path(args[i + 1])

    if output_dir is None:
        # Try to read from config
        try:
            import json

            from botwerk_bot.workspace.paths import resolve_paths

            paths = resolve_paths()
            if paths.config_path.exists():
                data = json.loads(paths.config_path.read_text(encoding="utf-8"))
                webui = data.get("webui", {})
                configured_dir = webui.get("frontend_dir", "")
                if configured_dir:
                    output_dir = Path(configured_dir)
        except Exception:  # noqa: BLE001
            pass

    if output_dir is None:
        from botwerk_bot.workspace.paths import resolve_paths

        paths = resolve_paths()
        output_dir = paths.botwerk_home / "frontend"

    # -- npm install -----------------------------------------------------------

    _console.print("[bold blue]Installing dependencies...[/bold blue]")

    try:
        result = subprocess.run(
            [npm_path, "install"],
            cwd=str(frontend_src),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            _console.print("[bold red]npm install failed:[/bold red]")
            _console.print(result.stderr or result.stdout)
            sys.exit(1)
    except subprocess.TimeoutExpired:
        _console.print("[bold red]npm install timed out (5 min).[/bold red]")
        sys.exit(1)
    except OSError as exc:
        _console.print(f"[bold red]Failed to run npm:[/bold red] {exc}")
        sys.exit(1)

    _console.print("[green]Dependencies installed.[/green]")

    # -- npm run build ---------------------------------------------------------

    _console.print("[bold blue]Building frontend...[/bold blue]")

    try:
        result = subprocess.run(
            [npm_path, "run", "build"],
            cwd=str(frontend_src),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            _console.print("[bold red]Build failed:[/bold red]")
            _console.print(result.stderr or result.stdout)
            sys.exit(1)
    except subprocess.TimeoutExpired:
        _console.print("[bold red]Build timed out (5 min).[/bold red]")
        sys.exit(1)
    except OSError as exc:
        _console.print(f"[bold red]Failed to run npm:[/bold red] {exc}")
        sys.exit(1)

    _console.print("[green]Build complete.[/green]")

    # -- Copy build output to frontend_dir ------------------------------------

    build_output = frontend_src / "build"
    if not build_output.is_dir():
        _console.print(
            f"[bold red]Build output not found at {build_output}[/bold red]\n"
            "Expected SvelteKit adapter-static output in frontend/build/."
        )
        sys.exit(1)

    _console.print(f"[bold blue]Copying build to {output_dir}...[/bold blue]")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove old files before copying
    for item in output_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    shutil.copytree(str(build_output), str(output_dir), dirs_exist_ok=True)

    _console.print(
        f"[bold green]Frontend deployed to {output_dir}[/bold green]\n"
        "[dim]Restart the bot for changes to take effect.[/dim]"
    )
