"""Pydantic schemas for the WebUI API."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


# -- Auth schemas ----------------------------------------------------------


class LoginRequest(BaseModel):
    """Credentials for login."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Response after successful login."""

    id: int
    username: str
    display_name: str
    is_admin: bool


class UserCreate(BaseModel):
    """Payload for creating a new user."""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)


class UserResponse(BaseModel):
    """Public user info returned by API endpoints."""

    id: int
    username: str
    display_name: str
    is_admin: bool
    created_at: datetime.datetime
    last_login: datetime.datetime | None = None


class TokenPayload(BaseModel):
    """Decoded JWT token payload."""

    user_id: int
    is_admin: bool
    exp: int


# -- Message schemas -------------------------------------------------------


class MessageCreate(BaseModel):
    """Payload for storing a new message."""

    agent_name: str
    role: str = Field(pattern=r"^(user|assistant|system)$")
    content: str
    metadata_json: str | None = None


class MessageResponse(BaseModel):
    """A stored message returned by the API."""

    id: int
    user_id: int
    agent_name: str
    role: str
    content: str
    metadata_json: str | None = None
    created_at: datetime.datetime
