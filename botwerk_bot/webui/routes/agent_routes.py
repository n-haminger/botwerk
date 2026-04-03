"""Agent-related API routes (stubs for Phase 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.models import AgentAssignment
from botwerk_bot.webui.schemas import TokenPayload


def create_agent_router(auth_dep: object) -> APIRouter:
    """Build and return the agent router."""
    router = APIRouter(prefix="/agents", tags=["agents"])

    @router.get("")
    async def list_agents(
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> list[dict[str, str]]:
        """List agents assigned to the current user.

        Admins see all agents (placeholder — full implementation in Phase 2).
        """
        result = await db.execute(
            select(AgentAssignment.agent_name).where(
                AgentAssignment.user_id == token.user_id,
            )
        )
        names = [row[0] for row in result.all()]

        # Return minimal stub objects.
        return [{"name": name} for name in names]

    return router
