"""Tests for BotwerkPaths and resolve_paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from botwerk_bot.workspace.paths import BotwerkPaths, resolve_paths


def test_workspace_property() -> None:
    paths = BotwerkPaths(
        botwerk_home=Path("/home/test/.botwerk"),
        home_defaults=Path("/opt/botwerk/workspace"),
        framework_root=Path("/opt/botwerk"),
    )
    assert paths.workspace == Path("/home/test/.botwerk/workspace")


def test_config_path() -> None:
    paths = BotwerkPaths(
        botwerk_home=Path("/home/test/.botwerk"),
        home_defaults=Path("/opt/botwerk/workspace"),
        framework_root=Path("/opt/botwerk"),
    )
    assert paths.config_path == Path("/home/test/.botwerk/config/config.json")


def test_sessions_path() -> None:
    paths = BotwerkPaths(
        botwerk_home=Path("/home/test/.botwerk"),
        home_defaults=Path("/opt/botwerk/workspace"),
        framework_root=Path("/opt/botwerk"),
    )
    assert paths.sessions_path == Path("/home/test/.botwerk/sessions.json")


def test_logs_dir() -> None:
    paths = BotwerkPaths(
        botwerk_home=Path("/home/test/.botwerk"),
        home_defaults=Path("/opt/botwerk/workspace"),
        framework_root=Path("/opt/botwerk"),
    )
    assert paths.logs_dir == Path("/home/test/.botwerk/logs")


def test_home_defaults() -> None:
    paths = BotwerkPaths(
        botwerk_home=Path("/x"),
        home_defaults=Path("/opt/botwerk/workspace"),
        framework_root=Path("/opt/botwerk"),
    )
    assert paths.home_defaults == Path("/opt/botwerk/workspace")


def test_resolve_paths_explicit() -> None:
    paths = resolve_paths(botwerk_home="/tmp/test_home", framework_root="/tmp/test_fw")
    assert paths.botwerk_home == Path("/tmp/test_home").resolve()
    assert paths.framework_root == Path("/tmp/test_fw").resolve()


def test_resolve_paths_env_vars() -> None:
    with patch.dict(
        os.environ, {"BOTWERK_HOME": "/tmp/env_home", "BOTWERK_FRAMEWORK_ROOT": "/tmp/env_fw"}
    ):
        paths = resolve_paths()
        assert paths.botwerk_home == Path("/tmp/env_home").resolve()
        assert paths.framework_root == Path("/tmp/env_fw").resolve()


def test_resolve_paths_defaults() -> None:
    with patch.dict(os.environ, {}, clear=True):
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BOTWERK_HOME", "BOTWERK_FRAMEWORK_ROOT")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            paths = resolve_paths()
            assert paths.botwerk_home == (Path.home() / ".botwerk").resolve()
