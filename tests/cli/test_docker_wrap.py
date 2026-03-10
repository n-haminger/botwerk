"""Tests for cli/base.py: docker_wrap helper."""

from __future__ import annotations

from pathlib import PureWindowsPath

from botwerk_bot.cli.base import CLIConfig, docker_wrap


def test_docker_wrap_without_container() -> None:
    cmd = ["claude", "-p", "hello"]
    cfg = CLIConfig(docker_container="", chat_id=123, working_dir="/workspace")
    result_cmd, cwd = docker_wrap(cmd, cfg)
    assert result_cmd == cmd
    assert cwd == "/workspace"


def test_docker_wrap_with_container() -> None:
    cmd = ["claude", "-p", "hello"]
    cfg = CLIConfig(docker_container="my-sandbox", chat_id=42, working_dir="/workspace")
    result_cmd, cwd = docker_wrap(cmd, cfg)
    assert result_cmd == [
        "docker",
        "exec",
        "-w",
        "/botwerk/workspace",
        "-e",
        "BOTWERK_CHAT_ID=42",
        "-e",
        "BOTWERK_AGENT_NAME=main",
        "-e",
        "BOTWERK_INTERAGENT_PORT=8799",
        "-e",
        "BOTWERK_HOME=/botwerk",
        "-e",
        "BOTWERK_SHARED_MEMORY_PATH=/botwerk/SHAREDMEMORY.md",
        "-e",
        "BOTWERK_INTERAGENT_HOST=host.docker.internal",
        "my-sandbox",
        "claude",
        "-p",
        "hello",
    ]
    assert cwd is None


def test_docker_wrap_interactive() -> None:
    cmd = ["gemini", "--output-format", "json"]
    cfg = CLIConfig(docker_container="my-sandbox", chat_id=42, working_dir="/workspace")
    result_cmd, cwd = docker_wrap(cmd, cfg, interactive=True)
    assert result_cmd == [
        "docker",
        "exec",
        "-i",
        "-w",
        "/botwerk/workspace",
        "-e",
        "BOTWERK_CHAT_ID=42",
        "-e",
        "BOTWERK_AGENT_NAME=main",
        "-e",
        "BOTWERK_INTERAGENT_PORT=8799",
        "-e",
        "BOTWERK_HOME=/botwerk",
        "-e",
        "BOTWERK_SHARED_MEMORY_PATH=/botwerk/SHAREDMEMORY.md",
        "-e",
        "BOTWERK_INTERAGENT_HOST=host.docker.internal",
        "my-sandbox",
        "gemini",
        "--output-format",
        "json",
    ]
    assert cwd is None


def test_docker_wrap_preserves_full_command() -> None:
    cmd = ["claude", "-p", "test", "--model", "opus", "--verbose"]
    cfg = CLIConfig(docker_container="sandbox", chat_id=1, working_dir="/w")
    result_cmd, _ = docker_wrap(cmd, cfg)
    assert result_cmd[-6:] == cmd


def test_docker_wrap_injects_chat_id() -> None:
    cmd = ["codex", "exec"]
    cfg = CLIConfig(docker_container="box", chat_id=999, working_dir="/w")
    result_cmd, _ = docker_wrap(cmd, cfg)
    assert "BOTWERK_CHAT_ID=999" in result_cmd


def test_docker_wrap_extra_env() -> None:
    cmd = ["gemini"]
    cfg = CLIConfig(docker_container="box", chat_id=1, working_dir="/w")
    result_cmd, _ = docker_wrap(cmd, cfg, extra_env={"FOO": "bar"})
    assert "-e" in result_cmd
    assert "FOO=bar" in result_cmd


# -- Multi-agent: sub-agent uses container-relative paths --------------------


def test_docker_wrap_sub_agent_container_paths() -> None:
    """Sub-agent working_dir maps to /botwerk/agents/<name>/workspace inside container."""
    cmd = ["claude", "-p", "hi"]
    cfg = CLIConfig(
        docker_container="sandbox",
        chat_id=1,
        working_dir="/home/user/.botwerk/agents/test/workspace",
        agent_name="test",
    )
    result_cmd, cwd = docker_wrap(cmd, cfg)
    assert cwd is None
    # -w sets correct sub-agent workspace
    w_idx = result_cmd.index("-w")
    assert result_cmd[w_idx + 1] == "/botwerk/agents/test/workspace"
    # BOTWERK_HOME is the sub-agent home inside the container
    assert "BOTWERK_HOME=/botwerk/agents/test" in result_cmd
    # Shared memory is at the root
    assert "BOTWERK_SHARED_MEMORY_PATH=/botwerk/SHAREDMEMORY.md" in result_cmd


def test_docker_wrap_main_agent_container_paths() -> None:
    """Main agent working_dir maps to /botwerk/workspace inside container."""
    cmd = ["claude", "-p", "hi"]
    cfg = CLIConfig(
        docker_container="sandbox",
        chat_id=1,
        working_dir="/home/user/.botwerk/workspace",
        agent_name="main",
    )
    result_cmd, _ = docker_wrap(cmd, cfg)
    w_idx = result_cmd.index("-w")
    assert result_cmd[w_idx + 1] == "/botwerk/workspace"
    assert "BOTWERK_HOME=/botwerk" in result_cmd
    assert "BOTWERK_SHARED_MEMORY_PATH=/botwerk/SHAREDMEMORY.md" in result_cmd


def test_docker_wrap_sub_agent_windows_paths_are_posix() -> None:
    """Windows host paths must be normalized to POSIX paths inside Docker."""
    cmd = ["gemini", "--output-format", "stream-json"]
    cfg = CLIConfig(
        docker_container="sandbox",
        chat_id=1,
        working_dir=PureWindowsPath(r"C:\Users\me\.botwerk\agents\seismic-bot\workspace"),
        agent_name="seismic-bot",
    )
    result_cmd, _ = docker_wrap(cmd, cfg, interactive=True)
    w_idx = result_cmd.index("-w")
    assert result_cmd[w_idx + 1] == "/botwerk/agents/seismic-bot/workspace"
    assert "BOTWERK_HOME=/botwerk/agents/seismic-bot" in result_cmd
