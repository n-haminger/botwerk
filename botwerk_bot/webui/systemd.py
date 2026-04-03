"""Generate a hardened systemd unit file for the Botwerk WebUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SystemdConfig:
    """Parameters for generating a systemd service unit."""

    user: str = "botwerk"
    group: str = "botwerk"
    working_directory: str = "/opt/botwerk"
    botwerk_home: str = "~/.botwerk"
    db_path: str = "~/.botwerk/webui.db"
    upload_dir: str = "~/.botwerk/webui_uploads"
    port: int = 8080
    environment: dict[str, str] = field(default_factory=dict)
    description: str = "Botwerk AI Assistant"
    exec_start: str = "/usr/local/bin/botwerk"


def generate_systemd_unit(config: SystemdConfig | None = None) -> str:
    """Generate a production-ready systemd unit file.

    The generated unit includes security hardening directives that restrict
    filesystem access, capabilities, and namespace usage.

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        The full contents of a systemd .service unit file.
    """
    if config is None:
        config = SystemdConfig()

    # Resolve ~ in paths for ReadWritePaths
    home = Path(config.botwerk_home).expanduser()
    db_parent = Path(config.db_path).expanduser().parent
    upload_dir = Path(config.upload_dir).expanduser()

    # Collect unique ReadWritePaths
    rw_paths: list[str] = []
    seen: set[str] = set()
    for p in [str(home), str(db_parent), str(upload_dir)]:
        if p not in seen:
            rw_paths.append(p)
            seen.add(p)

    # Build environment lines
    env_lines = ""
    for key, value in config.environment.items():
        env_lines += f"Environment={key}={value}\n"

    rw_paths_str = " ".join(rw_paths)

    unit = f"""\
[Unit]
Description={config.description}
After=network.target
Wants=network.target

[Service]
Type=simple
User={config.user}
Group={config.group}
WorkingDirectory={config.working_directory}
ExecStart={config.exec_start}
Restart=on-failure
RestartSec=5
{env_lines}
# --- Security hardening ---
ProtectSystem=strict
ProtectHome=read-only
NoNewPrivileges=true
CapabilityBoundingSet=
RestrictNamespaces=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
SystemCallArchitectures=native

# Writable paths for botwerk data
ReadWritePaths={rw_paths_str}

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=botwerk

[Install]
WantedBy=multi-user.target
"""
    return unit
