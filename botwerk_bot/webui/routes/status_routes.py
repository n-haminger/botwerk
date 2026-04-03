"""System status API routes — CPU, memory, disk, agent status, service control."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, HTTPException, status

from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)

_DEFAULT_AGENTS_PATH = Path.home() / ".botwerk" / "agents.json"
_RESTART_MARKER = Path.home() / ".botwerk" / "restart-requested"


def create_status_router(auth_dep: object) -> APIRouter:
    """Build and return the status router."""
    router = APIRouter(prefix="/status", tags=["status"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    @router.get("/system")
    async def system_status(
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Return CPU, memory, disk, and uptime info."""
        _require_admin(token)

        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time

        return {
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count(),
            },
            "memory": {
                "total": mem.total,
                "used": mem.used,
                "available": mem.available,
                "percent": mem.percent,
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent,
            },
            "uptime_seconds": uptime_seconds,
        }

    @router.get("/agents")
    async def agent_status(
        token: TokenPayload = Depends(auth_dep),
    ) -> list[dict]:
        """Return running agents with basic resource info."""
        _require_admin(token)

        agents_path = _DEFAULT_AGENTS_PATH
        if not agents_path.is_file():
            return []

        try:
            raw = json.loads(agents_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(raw, list):
            return []

        results = []
        for agent in raw:
            name = agent.get("name", "")
            if not name:
                continue

            # Try to find the agent's process by looking for its Linux user
            linux_user = agent.get("linux_user_name") or f"botwerk-{name}"
            agent_info: dict = {
                "name": name,
                "agent_type": agent.get("agent_type", "worker"),
                "linux_user": linux_user,
                "status": "stopped",
                "pid": None,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
            }

            # Check for running processes by this user
            try:
                for proc in psutil.process_iter(["pid", "username", "cpu_percent", "memory_info"]):
                    try:
                        if proc.info["username"] == linux_user:
                            agent_info["status"] = "running"
                            agent_info["pid"] = proc.info["pid"]
                            agent_info["cpu_percent"] += proc.info["cpu_percent"] or 0.0
                            mem_info = proc.info.get("memory_info")
                            if mem_info:
                                agent_info["memory_mb"] += mem_info.rss / (1024 * 1024)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:  # noqa: BLE001
                pass

            agent_info["memory_mb"] = round(agent_info["memory_mb"], 1)
            agent_info["cpu_percent"] = round(agent_info["cpu_percent"], 1)
            results.append(agent_info)

        return results

    @router.get("/service")
    async def service_status(
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Return botwerk service state via systemctl."""
        _require_admin(token)

        try:
            result = subprocess.run(
                ["systemctl", "status", "botwerk", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = result.stdout.strip()

            # Parse active state
            active_state = "unknown"
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("Active:"):
                    active_state = line.split(":", 1)[1].strip()
                    break

            return {
                "service": "botwerk",
                "active_state": active_state,
                "raw_output": output,
            }
        except subprocess.TimeoutExpired:
            return {
                "service": "botwerk",
                "active_state": "unknown",
                "raw_output": "Timed out checking service status",
            }
        except FileNotFoundError:
            return {
                "service": "botwerk",
                "active_state": "unknown",
                "raw_output": "systemctl not found",
            }

    @router.post("/restart-agent/{name}")
    async def restart_agent(
        name: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Restart a specific agent by touching its restart marker."""
        _require_admin(token)

        # Validate agent exists
        agents_path = _DEFAULT_AGENTS_PATH
        if agents_path.is_file():
            try:
                raw = json.loads(agents_path.read_text(encoding="utf-8"))
                if not any(a.get("name") == name for a in raw):
                    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
            except (json.JSONDecodeError, OSError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot read agents.json",
                ) from exc
        else:
            raise HTTPException(status_code=404, detail="No agents configured")

        # Touch restart marker for the agent
        marker = Path.home() / ".botwerk" / f"restart-{name}"
        try:
            marker.touch()
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create restart marker: {exc}",
            ) from exc

        return {"status": "restart_requested", "agent": name}

    @router.post("/restart-botwerk")
    async def restart_botwerk(
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Restart the botwerk service by touching the global restart marker."""
        _require_admin(token)

        try:
            _RESTART_MARKER.touch()
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create restart marker: {exc}",
            ) from exc

        return {"status": "restart_requested"}

    return router
