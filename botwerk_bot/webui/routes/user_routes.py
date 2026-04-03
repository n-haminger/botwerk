"""Admin user management API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.webui.auth import hash_password
from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.models import AgentAssignment, User
from botwerk_bot.webui.schemas import TokenPayload, UserResponse

logger = logging.getLogger(__name__)


class AdminUserCreate(BaseModel):
    """Payload for admin-created users."""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    """Payload for updating a user (admin or self)."""

    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    is_admin: bool | None = None


class AgentAssignmentUpdate(BaseModel):
    """Payload for updating a user's agent assignments."""

    agent_names: list[str]


class AgentAssignmentResponse(BaseModel):
    """Response with a user's assigned agent names."""

    user_id: int
    agent_names: list[str]


def create_user_router(auth_dep: object) -> APIRouter:
    """Build and return the admin user management router."""
    router = APIRouter(prefix="/admin/users", tags=["admin-users"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    @router.get("", response_model=list[UserResponse])
    async def list_users(
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> list[UserResponse]:
        """List all WebUI users. Admin only."""
        _require_admin(token)

        result = await db.execute(select(User).order_by(User.id))
        users = result.scalars().all()
        return [
            UserResponse(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                is_admin=u.is_admin,
                created_at=u.created_at,
                last_login=u.last_login,
            )
            for u in users
        ]

    @router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    async def create_user(
        body: AdminUserCreate,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:
        """Create a new user. Admin only."""
        _require_admin(token)

        # Check for duplicate username.
        existing = await db.execute(select(User).where(User.username == body.username))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{body.username}' already exists",
            )

        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            display_name=body.display_name or body.username,
            is_admin=body.is_admin,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info("User created by admin user_id=%d: %s", token.user_id, user.username)
        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login=user.last_login,
        )

    @router.put("/{user_id}", response_model=UserResponse)
    async def update_user(
        user_id: int,
        body: AdminUserUpdate,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:
        """Update a user. Admin can update anyone; non-admin can only update self (password/display_name)."""
        is_self = token.user_id == user_id
        if not token.is_admin and not is_self:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

        # Non-admin cannot change is_admin.
        if not token.is_admin and body.is_admin is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change admin status",
            )

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        if body.password is not None:
            user.password_hash = hash_password(body.password)
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.is_admin is not None:
            user.is_admin = body.is_admin

        await db.commit()
        await db.refresh(user)

        logger.info("User updated by user_id=%d: user_id=%d", token.user_id, user_id)
        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login=user.last_login,
        )

    @router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_user(
        user_id: int,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        """Delete a user. Admin only. Cannot delete yourself."""
        _require_admin(token)

        if token.user_id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete yourself",
            )

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        await db.delete(user)
        await db.commit()
        logger.info("User deleted by admin user_id=%d: user_id=%d", token.user_id, user_id)

    @router.put("/{user_id}/agents", response_model=AgentAssignmentResponse)
    async def set_user_agents(
        user_id: int,
        body: AgentAssignmentUpdate,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> AgentAssignmentResponse:
        """Set the agent assignments for a user. Admin only."""
        _require_admin(token)

        # Verify user exists.
        result = await db.execute(select(User).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Delete existing assignments.
        existing = await db.execute(
            select(AgentAssignment).where(AgentAssignment.user_id == user_id)
        )
        for assignment in existing.scalars().all():
            await db.delete(assignment)

        # Create new assignments.
        for name in body.agent_names:
            db.add(AgentAssignment(user_id=user_id, agent_name=name))

        await db.commit()

        logger.info(
            "Agent assignments updated for user_id=%d by admin user_id=%d: %s",
            user_id,
            token.user_id,
            body.agent_names,
        )
        return AgentAssignmentResponse(user_id=user_id, agent_names=body.agent_names)

    @router.get("/{user_id}/agents", response_model=AgentAssignmentResponse)
    async def get_user_agents(
        user_id: int,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> AgentAssignmentResponse:
        """Get the agent assignments for a user. Admin only."""
        _require_admin(token)

        # Verify user exists.
        result = await db.execute(select(User).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        result = await db.execute(
            select(AgentAssignment).where(AgentAssignment.user_id == user_id)
        )
        assignments = result.scalars().all()
        return AgentAssignmentResponse(
            user_id=user_id,
            agent_names=[a.agent_name for a in assignments],
        )

    return router
