"""Authentication API routes: login, logout, setup, current user."""

from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.webui.auth import (
    COOKIE_NAME,
    create_access_token,
    hash_password,
    verify_password,
)
from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.models import User
from botwerk_bot.webui.schemas import LoginRequest, LoginResponse, TokenPayload, UserCreate, UserResponse

logger = logging.getLogger(__name__)


def create_auth_router(
    secret_key: str, auth_dep: object, *, secure_cookies: bool = False
) -> APIRouter:
    """Build and return the auth router bound to the given secret key."""
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    async def setup_first_user(
        body: UserCreate,
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:
        """Create the first admin user. Only works when no users exist."""
        count = await db.scalar(select(func.count()).select_from(User))
        if count and count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Setup already completed — users exist",
            )

        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            display_name=body.display_name or body.username,
            is_admin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("WebUI first admin user created: %s", user.username)

        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login=user.last_login,
        )

    @router.post("/login", response_model=LoginResponse)
    async def login(
        body: LoginRequest,
        response: Response,
        db: AsyncSession = Depends(get_db),
    ) -> LoginResponse:
        """Authenticate and set an HTTP-only JWT cookie."""
        result = await db.execute(select(User).where(User.username == body.username))
        user = result.scalar_one_or_none()

        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        # Update last_login
        user.last_login = datetime.datetime.now(datetime.UTC)
        await db.commit()

        token = create_access_token(user.id, user.is_admin, secret_key)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            secure=secure_cookies,
            max_age=86400,
            path="/",
        )

        return LoginResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        )

    @router.post("/logout")
    async def logout(response: Response) -> dict[str, str]:
        """Clear the auth cookie."""
        response.delete_cookie(key=COOKIE_NAME, path="/")
        return {"status": "ok"}

    @router.get("/me", response_model=UserResponse)
    async def get_me(
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:
        """Return the currently authenticated user."""
        result = await db.execute(select(User).where(User.id == token.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login=user.last_login,
        )

    return router
