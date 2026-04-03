"""Admin cron job overview API routes."""

from __future__ import annotations

import logging
from pathlib import Path

from croniter import croniter
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException, status

from botwerk_bot.cron.manager import CronJob, CronManager
from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)

_DEFAULT_CRON_PATH = Path.home() / ".botwerk" / "cron_jobs.json"


def _get_cron_path() -> Path:
    """Return the cron jobs file path (mockable in tests)."""
    return _DEFAULT_CRON_PATH


def _next_run_iso(schedule: str, timezone: str = "") -> str | None:
    """Calculate the next run time for a cron schedule expression."""
    try:
        base = datetime.now(UTC)
        cron = croniter(schedule, base)
        next_dt = cron.get_next(datetime)
        return next_dt.isoformat()
    except (ValueError, KeyError):
        return None


def _job_to_dict(job: CronJob) -> dict:
    """Convert a CronJob to an API response dict with next_run."""
    d = job.to_dict()
    d["next_run"] = _next_run_iso(job.schedule, job.timezone) if job.enabled else None
    return d


def create_cron_router(auth_dep: object) -> APIRouter:
    """Build and return the admin cron router."""
    router = APIRouter(prefix="/admin/cron", tags=["admin-cron"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    def _get_manager() -> CronManager:
        """Load a CronManager from the cron jobs file."""
        cron_path = _get_cron_path()
        return CronManager(jobs_path=cron_path)

    @router.get("")
    async def list_cron_jobs(
        token: TokenPayload = Depends(auth_dep),
    ) -> list[dict]:
        """List all cron jobs with next-run times."""
        _require_admin(token)
        manager = _get_manager()
        return [_job_to_dict(job) for job in manager.list_jobs()]

    @router.post("/{job_id}/enable")
    async def enable_cron_job(
        job_id: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Enable a cron job."""
        _require_admin(token)
        manager = _get_manager()

        job = manager.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cron job '{job_id}' not found",
            )

        manager.set_enabled(job_id, enabled=True)
        logger.info("Cron job '%s' enabled by user_id=%d", job_id, token.user_id)
        return {"status": "ok", "job_id": job_id, "enabled": True}

    @router.post("/{job_id}/disable")
    async def disable_cron_job(
        job_id: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Disable a cron job."""
        _require_admin(token)
        manager = _get_manager()

        job = manager.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cron job '{job_id}' not found",
            )

        manager.set_enabled(job_id, enabled=False)
        logger.info("Cron job '%s' disabled by user_id=%d", job_id, token.user_id)
        return {"status": "ok", "job_id": job_id, "enabled": False}

    @router.post("/{job_id}/trigger")
    async def trigger_cron_job(
        job_id: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Trigger an immediate run of a cron job by updating its status."""
        _require_admin(token)
        manager = _get_manager()

        job = manager.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cron job '{job_id}' not found",
            )

        # Mark as triggered — the cron observer will pick this up.
        manager.update_run_status(job_id, status="triggered")
        logger.info("Cron job '%s' triggered by user_id=%d", job_id, token.user_id)
        return {"status": "ok", "job_id": job_id, "triggered": True}

    return router
