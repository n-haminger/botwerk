"""Tests for botwerk_bot.webui.database — engine init, session, and models."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from sqlalchemy.exc import IntegrityError

from botwerk_bot.webui.database import close_db, get_db, init_db
from botwerk_bot.webui.models import AgentAssignment, Message, User


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path: Path):
    db_path = str(tmp_path / "test_init.db")
    engine = await init_db(db_path)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = {row[0] for row in result.all()}
        assert "users" in tables
        assert "messages" in tables
        assert "agent_assignments" in tables
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path: Path):
    db_path = str(tmp_path / "test_wal.db")
    engine = await init_db(db_path)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
        assert mode == "wal"
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_user_crud(db_session):
    user = User(
        username="testuser",
        password_hash="fakehash",
        display_name="Test User",
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.id > 0

    result = await db_session.execute(select(User).where(User.username == "testuser"))
    loaded = result.scalar_one()
    assert loaded.display_name == "Test User"
    assert loaded.is_admin is False


@pytest.mark.asyncio
async def test_message_with_foreign_key(db_session):
    user = User(username="msguser", password_hash="hash", display_name="Msg User")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    msg = Message(
        user_id=user.id,
        agent_name="main",
        role="user",
        content="Hello, world!",
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.id is not None
    assert msg.user_id == user.id
    assert msg.role == "user"


@pytest.mark.asyncio
async def test_agent_assignment(db_session):
    user = User(username="assigned", password_hash="hash", display_name="Assigned")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assignment = AgentAssignment(user_id=user.id, agent_name="main")
    db_session.add(assignment)
    await db_session.commit()

    result = await db_session.execute(
        select(AgentAssignment).where(AgentAssignment.user_id == user.id)
    )
    loaded = result.scalar_one()
    assert loaded.agent_name == "main"


@pytest.mark.asyncio
async def test_unique_username_constraint(db_session):
    """Inserting two users with the same username must fail."""
    u1 = User(username="duplicate", password_hash="hash1", display_name="First")
    db_session.add(u1)
    await db_session.commit()

    u2 = User(username="duplicate", password_hash="hash2", display_name="Second")
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_unique_agent_assignment_constraint(db_session):
    """Duplicate (user_id, agent_name) assignments must fail."""
    user = User(username="unique_aa", password_hash="hash", display_name="AA")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    a1 = AgentAssignment(user_id=user.id, agent_name="main")
    db_session.add(a1)
    await db_session.commit()

    a2 = AgentAssignment(user_id=user.id, agent_name="main")
    db_session.add(a2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_user_default_values(db_session):
    """Test that default column values are set correctly."""
    user = User(username="defaults", password_hash="hash", display_name="Defaults")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.is_admin is False
    assert user.created_at is not None
    assert user.last_login is None


@pytest.mark.asyncio
async def test_message_foreign_key_column_exists(db_session):
    """Message model has a user_id foreign key column pointing to users.id."""
    from sqlalchemy import inspect as sa_inspect

    async with db_session.bind.connect() as conn:
        fks = await conn.run_sync(
            lambda sync_conn: sa_inspect(sync_conn).get_foreign_keys("messages")
        )
    user_fks = [fk for fk in fks if fk["referred_table"] == "users"]
    assert len(user_fks) == 1
    assert "user_id" in user_fks[0]["constrained_columns"]


@pytest.mark.asyncio
async def test_user_messages_relationship(db_session):
    """User.messages relationship loads associated messages."""
    user = User(username="reluser", password_hash="hash", display_name="Rel")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    for i in range(3):
        db_session.add(Message(
            user_id=user.id, agent_name="main", role="user", content=f"msg {i}"
        ))
    await db_session.commit()

    result = await db_session.execute(
        select(User).where(User.id == user.id)
    )
    loaded = result.scalar_one()
    await db_session.refresh(loaded, attribute_names=["messages"])
    assert len(loaded.messages) == 3


@pytest.mark.asyncio
async def test_get_db_without_init_raises():
    """get_db should raise RuntimeError if init_db was never called."""
    import botwerk_bot.webui.database as db_mod

    # Ensure the module-level factory is None.
    original = db_mod._session_factory
    db_mod._session_factory = None
    try:
        gen = get_db()
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await gen.__anext__()
    finally:
        db_mod._session_factory = original


@pytest.mark.asyncio
async def test_close_db_idempotent(tmp_path):
    """close_db can be called multiple times without error."""
    db_path = str(tmp_path / "test_close.db")
    await init_db(db_path)
    await close_db()
    await close_db()  # second call should be a no-op
