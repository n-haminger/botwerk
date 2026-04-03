"""Tests for message history API routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.webui.auth import COOKIE_NAME, create_access_token
from botwerk_bot.webui.models import AgentAssignment, Message, User

from .conftest import TEST_SECRET


def _make_token(user_id: int, is_admin: bool = False) -> str:
    return create_access_token(user_id, is_admin, TEST_SECRET)


async def _setup_user_with_agent(db_session: AsyncSession) -> tuple[User, str]:
    """Create a user with an agent assignment, return (user, token)."""
    user = User(username="testuser", password_hash="hash", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(AgentAssignment(user_id=user.id, agent_name="main"))
    await db_session.commit()

    token = _make_token(user.id)
    return user, token


async def _add_messages(
    db_session: AsyncSession, user_id: int, agent_name: str, count: int
) -> list[Message]:
    """Add test messages and return them."""
    messages = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msg = Message(
            user_id=user_id,
            agent_name=agent_name,
            role=role,
            content=f"Message {i}",
        )
        db_session.add(msg)
        messages.append(msg)
    await db_session.commit()
    for m in messages:
        await db_session.refresh(m)
    return messages


# -- Auth checks ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_without_auth(client: AsyncClient):
    """Unauthenticated request returns 401."""
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_messages_no_access(client: AsyncClient, db_session: AsyncSession):
    """User without agent assignment gets 403."""
    user = User(username="noagent", password_hash="hash", display_name="No", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user.id)
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 403
    client.cookies.clear()


# -- GET /api/messages/{agent_name} -------------------------------------------


@pytest.mark.asyncio
async def test_messages_empty(client: AsyncClient, db_session: AsyncSession):
    """No messages returns empty list."""
    user, token = await _setup_user_with_agent(db_session)
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 200
    assert resp.json() == []
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_returns_chronological(client: AsyncClient, db_session: AsyncSession):
    """Messages are returned in chronological order (oldest first)."""
    user, token = await _setup_user_with_agent(db_session)
    await _add_messages(db_session, user.id, "main", 5)

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5

    # Check chronological order.
    ids = [m["id"] for m in data]
    assert ids == sorted(ids)
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_pagination_limit(client: AsyncClient, db_session: AsyncSession):
    """Limit parameter caps the number of returned messages."""
    user, token = await _setup_user_with_agent(db_session)
    await _add_messages(db_session, user.id, "main", 10)

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_pagination_before_id(client: AsyncClient, db_session: AsyncSession):
    """before_id returns only messages with id < before_id."""
    user, token = await _setup_user_with_agent(db_session)
    messages = await _add_messages(db_session, user.id, "main", 10)

    # Get the 6th message ID as the cursor.
    cursor_id = messages[5].id

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get(f"/api/messages/main?before_id={cursor_id}")
    assert resp.status_code == 200
    data = resp.json()
    # Should return messages 0-4 (IDs before cursor_id).
    assert all(m["id"] < cursor_id for m in data)
    assert len(data) == 5
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_pagination_before_id_and_limit(
    client: AsyncClient, db_session: AsyncSession
):
    """Combining before_id and limit works correctly."""
    user, token = await _setup_user_with_agent(db_session)
    messages = await _add_messages(db_session, user.id, "main", 10)

    cursor_id = messages[7].id

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get(f"/api/messages/main?before_id={cursor_id}&limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Should be the 3 most recent messages before cursor_id.
    assert all(m["id"] < cursor_id for m in data)
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_only_own_messages(client: AsyncClient, db_session: AsyncSession):
    """User only sees their own messages, not another user's."""
    user1, token1 = await _setup_user_with_agent(db_session)

    # Create a second user with the same agent.
    user2 = User(username="other", password_hash="hash", display_name="Other", is_admin=False)
    db_session.add(user2)
    await db_session.commit()
    await db_session.refresh(user2)
    db_session.add(AgentAssignment(user_id=user2.id, agent_name="main"))
    await db_session.commit()

    await _add_messages(db_session, user1.id, "main", 3)
    await _add_messages(db_session, user2.id, "main", 5)

    client.cookies.set(COOKIE_NAME, token1)
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(m["user_id"] == user1.id for m in data)
    client.cookies.clear()


@pytest.mark.asyncio
async def test_messages_different_agents_isolated(
    client: AsyncClient, db_session: AsyncSession
):
    """Messages for different agents are isolated."""
    user, token = await _setup_user_with_agent(db_session)
    db_session.add(AgentAssignment(user_id=user.id, agent_name="helper"))
    await db_session.commit()

    await _add_messages(db_session, user.id, "main", 3)
    await _add_messages(db_session, user.id, "helper", 7)

    client.cookies.set(COOKIE_NAME, token)

    resp = await client.get("/api/messages/main")
    assert len(resp.json()) == 3

    resp = await client.get("/api/messages/helper")
    assert len(resp.json()) == 7
    client.cookies.clear()


# -- GET /api/messages/{agent_name}/count -------------------------------------


@pytest.mark.asyncio
async def test_message_count_empty(client: AsyncClient, db_session: AsyncSession):
    """Count returns 0 when no messages exist."""
    user, token = await _setup_user_with_agent(db_session)
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main/count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    client.cookies.clear()


@pytest.mark.asyncio
async def test_message_count(client: AsyncClient, db_session: AsyncSession):
    """Count returns the correct number of messages."""
    user, token = await _setup_user_with_agent(db_session)
    await _add_messages(db_session, user.id, "main", 7)

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main/count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 7
    client.cookies.clear()


@pytest.mark.asyncio
async def test_message_count_no_access(client: AsyncClient, db_session: AsyncSession):
    """Count returns 403 without agent assignment."""
    user = User(username="noagent", password_hash="hash", display_name="No", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user.id)
    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main/count")
    assert resp.status_code == 403
    client.cookies.clear()


# -- Response schema -----------------------------------------------------------


@pytest.mark.asyncio
async def test_message_response_fields(client: AsyncClient, db_session: AsyncSession):
    """Message responses contain all expected fields."""
    user, token = await _setup_user_with_agent(db_session)
    msg = Message(
        user_id=user.id,
        agent_name="main",
        role="user",
        content="Hello",
        metadata_json='{"key": "value"}',
    )
    db_session.add(msg)
    await db_session.commit()

    client.cookies.set(COOKIE_NAME, token)
    resp = await client.get("/api/messages/main")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    m = data[0]
    assert "id" in m
    assert m["user_id"] == user.id
    assert m["agent_name"] == "main"
    assert m["role"] == "user"
    assert m["content"] == "Hello"
    assert m["metadata_json"] == '{"key": "value"}'
    assert "created_at" in m
    client.cookies.clear()
