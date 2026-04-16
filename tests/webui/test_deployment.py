"""Tests for deployment polish: systemd, health endpoint, build-frontend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from botwerk_bot.webui.systemd import SystemdConfig, generate_systemd_unit

from .conftest import TEST_SECRET


# ---------------------------------------------------------------------------
# systemd unit generation
# ---------------------------------------------------------------------------


class TestSystemdUnit:
    """Test generate_systemd_unit produces expected directives."""

    def test_default_config(self) -> None:
        unit = generate_systemd_unit()
        assert "ProtectSystem=strict" in unit
        assert "RestrictNamespaces=true" in unit
        assert "PrivateTmp=true" in unit
        assert "After=network.target" in unit
        assert "WantedBy=multi-user.target" in unit
        assert "Restart=on-failure" in unit

    def test_hardening_lite_drops_sudo_incompatible_directives(self) -> None:
        """Hardening-lite must NOT emit directives that block sudo.

        Botwerk spawns terminals, manages Linux users, and applies
        permission templates via ``sudo -u`` — any directive that
        prevents privilege transitions breaks that model.
        """
        unit = generate_systemd_unit()
        active = [
            line.strip()
            for line in unit.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        forbidden = (
            "NoNewPrivileges=true",
            "CapabilityBoundingSet=",
            "RestrictSUIDSGID=true",
            "ProtectHome=read-only",
        )
        for directive in forbidden:
            matches = [ln for ln in active if ln.startswith(directive)]
            assert not matches, f"sudo-incompatible directive leaked: {directive}"

    def test_custom_user_and_port(self) -> None:
        config = SystemdConfig(user="myuser", group="mygroup", port=9090)
        unit = generate_systemd_unit(config)
        assert "User=myuser" in unit
        assert "Group=mygroup" in unit

    def test_readwrite_paths(self) -> None:
        config = SystemdConfig(
            botwerk_home="/home/test/.botwerk",
            db_path="/home/test/.botwerk/webui.db",
            upload_dir="/home/test/.botwerk/webui_uploads",
        )
        unit = generate_systemd_unit(config)
        assert "ReadWritePaths=" in unit
        assert "/home/test/.botwerk" in unit
        assert "/home/test/.botwerk/webui_uploads" in unit

    def test_environment_variables(self) -> None:
        config = SystemdConfig(environment={"FOO": "bar", "BAZ": "qux"})
        unit = generate_systemd_unit(config)
        assert "Environment=FOO=bar" in unit
        assert "Environment=BAZ=qux" in unit

    def test_security_hardening_directives(self) -> None:
        unit = generate_systemd_unit()
        assert "ProtectKernelTunables=true" in unit
        assert "ProtectKernelModules=true" in unit
        assert "ProtectControlGroups=true" in unit
        assert "RestrictRealtime=true" in unit
        assert "LockPersonality=true" in unit
        assert "SystemCallArchitectures=native" in unit

    def test_working_directory(self) -> None:
        config = SystemdConfig(working_directory="/srv/botwerk")
        unit = generate_systemd_unit(config)
        assert "WorkingDirectory=/srv/botwerk" in unit

    def test_description(self) -> None:
        config = SystemdConfig(description="My Custom Bot")
        unit = generate_systemd_unit(config)
        assert "Description=My Custom Bot" in unit


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Test the enhanced /health endpoint."""

    @pytest_asyncio.fixture
    async def health_client(self, webui_app):
        transport = ASGITransport(app=webui_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_health_returns_expected_fields(self, health_client: AsyncClient) -> None:
        resp = await health_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "webui"
        assert "version" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert "database" in data
        assert "active_agents" in data
        assert "websocket_clients" in data

    @pytest.mark.asyncio
    async def test_health_version_is_string(self, health_client: AsyncClient) -> None:
        resp = await health_client.get("/health")
        data = resp.json()
        assert isinstance(data["version"], str)

    @pytest.mark.asyncio
    async def test_health_uptime_positive(self, health_client: AsyncClient) -> None:
        resp = await health_client.get("/health")
        data = resp.json()
        assert data["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# build-frontend command (mocked subprocess)
# ---------------------------------------------------------------------------


class TestBuildFrontend:
    """Test the build-frontend CLI command with mocked subprocess."""

    @patch("botwerk_bot.cli_commands.build_frontend.subprocess.run")
    @patch("botwerk_bot.cli_commands.build_frontend._find_npm", return_value="/usr/bin/npm")
    @patch("botwerk_bot.cli_commands.build_frontend._find_node", return_value="/usr/bin/node")
    def test_missing_frontend_dir(
        self, mock_node: MagicMock, mock_npm: MagicMock, mock_run: MagicMock
    ) -> None:
        from botwerk_bot.cli_commands.build_frontend import cmd_build_frontend

        with pytest.raises(SystemExit):
            cmd_build_frontend(["--source", "/nonexistent/frontend"])

    @patch("botwerk_bot.cli_commands.build_frontend._find_npm", return_value=None)
    @patch("botwerk_bot.cli_commands.build_frontend._find_node", return_value="/usr/bin/node")
    def test_missing_npm(self, mock_node: MagicMock, mock_npm: MagicMock) -> None:
        from botwerk_bot.cli_commands.build_frontend import cmd_build_frontend

        with pytest.raises(SystemExit):
            cmd_build_frontend()

    @patch("botwerk_bot.cli_commands.build_frontend._find_node", return_value=None)
    def test_missing_node(self, mock_node: MagicMock) -> None:
        from botwerk_bot.cli_commands.build_frontend import cmd_build_frontend

        with pytest.raises(SystemExit):
            cmd_build_frontend()

    @patch("botwerk_bot.cli_commands.build_frontend.shutil.copytree")
    @patch("botwerk_bot.cli_commands.build_frontend.subprocess.run")
    @patch("botwerk_bot.cli_commands.build_frontend._find_npm", return_value="/usr/bin/npm")
    @patch("botwerk_bot.cli_commands.build_frontend._find_node", return_value="/usr/bin/node")
    def test_successful_build(
        self,
        mock_node: MagicMock,
        mock_npm: MagicMock,
        mock_run: MagicMock,
        mock_copytree: MagicMock,
        tmp_path,
    ) -> None:
        from botwerk_bot.cli_commands.build_frontend import cmd_build_frontend

        # Create a fake frontend directory with build output
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()
        build_dir = frontend_dir / "build"
        build_dir.mkdir()
        (build_dir / "index.html").write_text("<html></html>")

        output_dir = tmp_path / "output"

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        cmd_build_frontend([
            "--source", str(frontend_dir),
            "--output", str(output_dir),
        ])

        # npm install and npm run build should have been called
        assert mock_run.call_count == 2

    @patch("botwerk_bot.cli_commands.build_frontend.subprocess.run")
    @patch("botwerk_bot.cli_commands.build_frontend._find_npm", return_value="/usr/bin/npm")
    @patch("botwerk_bot.cli_commands.build_frontend._find_node", return_value="/usr/bin/node")
    def test_npm_install_failure(
        self,
        mock_node: MagicMock,
        mock_npm: MagicMock,
        mock_run: MagicMock,
        tmp_path,
    ) -> None:
        from botwerk_bot.cli_commands.build_frontend import cmd_build_frontend

        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()

        mock_run.return_value = MagicMock(returncode=1, stderr="Error", stdout="")

        with pytest.raises(SystemExit):
            cmd_build_frontend(["--source", str(frontend_dir)])
