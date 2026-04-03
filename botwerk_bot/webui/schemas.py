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


# -- File schemas -----------------------------------------------------------


class FileResponse(BaseModel):
    """Metadata for an uploaded file."""

    id: int
    name: str
    mime: str
    size: int
    url: str
    thumbnail_url: str | None = None
    created_at: datetime.datetime


# -- Message schemas -------------------------------------------------------


# -- Agent schemas ---------------------------------------------------------


class AgentCreate(BaseModel):
    """Payload for creating a new agent."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    provider: str | None = None
    model: str | None = None
    agent_type: str = Field(default="worker", pattern=r"^(worker|management)$")
    linux_user: bool = False
    linux_user_name: str | None = None
    permission_template: str | None = None
    trust_level: str = Field(default="restricted", pattern=r"^(privileged|restricted)$")
    can_contact: list[str] = Field(default_factory=list)
    accept_from: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    """Payload for updating an agent."""

    provider: str | None = None
    model: str | None = None
    agent_type: str | None = None
    linux_user: bool | None = None
    linux_user_name: str | None = None
    permission_template: str | None = None
    trust_level: str | None = None
    can_contact: list[str] | None = None
    accept_from: list[str] | None = None
    manager: str | None = None
    workers: list[str] | None = None


class AgentResponse(BaseModel):
    """Agent info returned by API endpoints."""

    name: str
    provider: str | None = None
    model: str | None = None
    agent_type: str = "worker"
    linux_user: bool = False
    trust_level: str = "restricted"
    can_contact: list[str] = Field(default_factory=list)
    accept_from: list[str] = Field(default_factory=list)
    status: str = "unknown"
    manager: str | None = None
    workers: list[str] = Field(default_factory=list)


class AgentHierarchyNode(BaseModel):
    """A node in the agent hierarchy tree."""

    name: str
    agent_type: str = "worker"
    status: str = "unknown"
    workers: list[AgentHierarchyNode] = Field(default_factory=list)


class AgentHierarchyResponse(BaseModel):
    """Full agent hierarchy tree."""

    roots: list[AgentHierarchyNode] = Field(default_factory=list)


class PermissionTemplateResponse(BaseModel):
    """A permission template description."""

    name: str
    description: str
    groups: list[str]
    sudo_rules: list[str]


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
