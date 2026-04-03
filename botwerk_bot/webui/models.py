"""SQLAlchemy 2.0 ORM models for the WebUI."""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all WebUI ORM models."""


class User(Base):
    """A WebUI user account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    last_login: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    messages: Mapped[list[Message]] = relationship(back_populates="user")
    assignments: Mapped[list[AgentAssignment]] = relationship(back_populates="user")


class Message(Base):
    """A chat message between a user and an agent."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )

    user: Mapped[User] = relationship(back_populates="messages")


class File(Base):
    """An uploaded file tracked by the WebUI."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    original_name: Mapped[str] = mapped_column(String(256), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )

    user: Mapped[User] = relationship()


class AgentAssignment(Base):
    """Maps which users can access which agents."""

    __tablename__ = "agent_assignments"
    __table_args__ = (UniqueConstraint("user_id", "agent_name"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(64), primary_key=True)

    user: Mapped[User] = relationship(back_populates="assignments")
