"""Message history API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.models import AgentAssignment, Message
from botwerk_bot.webui.schemas import MessageResponse, TokenPayload


def create_message_router(auth_dep: object) -> APIRouter:
    """Build and return the message history router."""
    router = APIRouter(prefix="/messages", tags=["messages"])

    async def _check_agent_access(
        user_id: int, agent_name: str, db: AsyncSession
    ) -> None:
        """Raise 403 if the user has no assignment for this agent."""
        result = await db.execute(
            select(AgentAssignment).where(
                AgentAssignment.user_id == user_id,
                AgentAssignment.agent_name == agent_name,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this agent",
            )

    @router.get("/{agent_name}", response_model=list[MessageResponse])
    async def get_messages(
        agent_name: str,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
        before_id: int | None = Query(None, description="Return messages before this ID"),
        limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
    ) -> list[MessageResponse]:
        """Return paginated message history for an agent, newest first."""
        await _check_agent_access(token.user_id, agent_name, db)

        query = (
            select(Message)
            .where(
                Message.user_id == token.user_id,
                Message.agent_name == agent_name,
            )
            .order_by(Message.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            query = query.where(Message.id < before_id)

        result = await db.execute(query)
        messages = result.scalars().all()

        return [
            MessageResponse(
                id=m.id,
                user_id=m.user_id,
                agent_name=m.agent_name,
                role=m.role,
                content=m.content,
                metadata_json=m.metadata_json,
                created_at=m.created_at,
            )
            for m in reversed(messages)  # Return in chronological order.
        ]

    @router.get("/{agent_name}/count")
    async def get_message_count(
        agent_name: str,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, int]:
        """Return the total message count for an agent."""
        await _check_agent_access(token.user_id, agent_name, db)

        count = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.user_id == token.user_id,
                Message.agent_name == agent_name,
            )
        )
        return {"count": count or 0}

    return router
