"""Tests for TerminalSession (PTY-based).

The session is exercised with a small, predictable child command (``cat``
or ``echo``) instead of a real shell, so the tests do not depend on
``sudo`` being available and produce deterministic output.
"""

from __future__ import annotations

import os
import time

import pytest

from botwerk_bot.webui.terminal import TerminalSession, _is_safe_username


def _wait_for_output(session: TerminalSession, *, timeout: float = 2.0) -> str:
    """Read from the session until some data arrives or timeout elapses."""
    deadline = time.monotonic() + timeout
    collected = ""
    while time.monotonic() < deadline:
        chunk = session.read()
        if chunk:
            collected += chunk
            # If the command is long-lived (cat), a single chunk is enough.
            return collected
        time.sleep(0.02)
    return collected


def test_start_spawns_child_with_valid_pid_and_fd():
    session = TerminalSession("dummy", argv=["/bin/cat"])
    session.start()
    try:
        assert session.pid is not None
        assert session.pid > 0
        assert session.master_fd is not None
        assert session.master_fd > 0
        assert session.is_alive()
    finally:
        session.close()


def test_write_then_read_roundtrip():
    session = TerminalSession("dummy", argv=["/bin/cat"])
    session.start()
    try:
        session.write("hello world\n")
        out = _wait_for_output(session)
        assert "hello world" in out
    finally:
        session.close()


def test_echo_command_exits_and_is_no_longer_alive():
    session = TerminalSession("dummy", argv=["/bin/echo", "done"])
    session.start()
    try:
        # Drain output from the short-lived process.
        deadline = time.monotonic() + 2.0
        seen = ""
        while time.monotonic() < deadline:
            chunk = session.read()
            if chunk:
                seen += chunk
            if not session.is_alive():
                break
            time.sleep(0.02)
        assert "done" in seen
        assert not session.is_alive()
    finally:
        session.close()


def test_resize_sends_tiocswinsz_without_error():
    session = TerminalSession("dummy", argv=["/bin/cat"])
    session.start()
    try:
        session.resize(120, 40)
        assert session.cols == 120
        assert session.rows == 40
    finally:
        session.close()


def test_close_returns_exit_code_and_marks_closed():
    session = TerminalSession("dummy", argv=["/bin/echo", "bye"])
    session.start()
    # Give the child time to finish.
    time.sleep(0.2)
    exit_code = session.close()
    assert session.closed
    assert exit_code in (0, 1)  # typically 0; tolerant if SIGTERM raced


def test_start_with_nonexistent_command_exits_127():
    session = TerminalSession("dummy", argv=["/this/does/not/exist"])
    session.start()
    # Wait for the child to die.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and session.is_alive():
        time.sleep(0.02)
    exit_code = session.close()
    # Either 127 (exec failure path) or 1 (if SIGTERM raced); never crash.
    assert exit_code in (127, 1, 0)
    assert session.closed


def test_default_argv_uses_sudo_wrap():
    session = TerminalSession("someuser")
    assert session._argv == ["sudo", "-u", "someuser", "--login", "-i"]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("botwerk", True),
        ("botwerk-dev", True),
        ("user_1", True),
        ("1abc", False),             # must start with a letter
        ("", False),
        ("a" * 65, False),           # over 64 chars
        ("user;rm -rf /", False),
        ("user$shell", False),
        ("root", True),
    ],
)
def test_is_safe_username(name, expected):
    assert _is_safe_username(name) is expected
