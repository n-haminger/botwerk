"""Tests for WebSocket chat handler."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from botwerk_bot.webui.auth import COOKIE_NAME, create_access_token
from botwerk_bot.webui.chat_service import ChatResult, ChatService
from botwerk_bot.webui.models import AgentAssignment, User

from .conftest import TEST_SECRET


def _make_token(user_id: int = 1, is_admin: bool = False) -> str:
    return create_access_token(user_id, is_admin, TEST_SECRET)


@pytest.mark.asyncio
async def test_ws_no_cookie_rejected(webui_app):
    """WebSocket without auth cookie is closed with 4001."""
    client = TestClient(webui_app)
    with pytest.raises(Exception):  # noqa: B017, PT011
        with client.websocket_connect("/ws/chat"):
            pass  # Should not reach here.


@pytest.mark.asyncio
async def test_ws_invalid_cookie_rejected(webui_app):
    """WebSocket with invalid JWT cookie is closed."""
    client = TestClient(webui_app)
    with pytest.raises(Exception):  # noqa: B017, PT011
        with client.websocket_connect(
            "/ws/chat",
            cookies={COOKIE_NAME: "garbage-token"},
        ):
            pass


@pytest.mark.asyncio
async def test_ws_valid_cookie_accepted(webui_app, db_session):
    """WebSocket with valid JWT cookie is accepted."""
    # Create a user.
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        # Connection accepted — send a subscribe to verify it works.
        ws.send_json({"type": "subscribe", "channel": "nonexistent"})
        resp = ws.receive_json()
        # Should get error since user has no assignment.
        assert resp["type"] == "error"
        assert resp["channel"] == "nonexistent"


@pytest.mark.asyncio
async def test_ws_subscribe_and_access_denied(webui_app, db_session):
    """Subscribe to a channel without assignment returns access denied."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "subscribe", "channel": "main"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "Access denied" in resp["content"]


@pytest.mark.asyncio
async def test_ws_subscribe_success(webui_app, db_session):
    """Subscribe to a channel with valid assignment succeeds."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(AgentAssignment(user_id=user.id, agent_name="main"))
    await db_session.commit()

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "subscribe", "channel": "main"})
        resp = ws.receive_json()
        assert resp["type"] == "subscribed"
        assert resp["channel"] == "main"


@pytest.mark.asyncio
async def test_ws_message_without_subscribe(webui_app, db_session):
    """Sending a message to a non-subscribed channel returns error."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "message", "channel": "main", "content": "hello"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "Not subscribed" in resp["content"]


@pytest.mark.asyncio
async def test_ws_message_flow(webui_app, db_session):
    """Full message flow: subscribe, send, receive stream_start/stream_end."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(AgentAssignment(user_id=user.id, agent_name="main"))
    await db_session.commit()

    # Mock the chat service to return a simple result.
    mock_service = webui_app.state.chat_service
    original_handle = mock_service.handle_message

    async def mock_handle(agent_name, session_key, text, **kwargs):
        # Call on_text_delta to simulate streaming.
        if kwargs.get("on_text_delta"):
            await kwargs["on_text_delta"]("Hello ")
            await kwargs["on_text_delta"]("world!")
        return ChatResult(text="Hello world!")

    mock_service.handle_message = mock_handle

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        # Subscribe.
        ws.send_json({"type": "subscribe", "channel": "main"})
        resp = ws.receive_json()
        assert resp["type"] == "subscribed"

        # Send message.
        ws.send_json({"type": "message", "channel": "main", "content": "hi"})

        # Expect: stream_start, stream_delta x2, stream_end.
        start = ws.receive_json()
        assert start["type"] == "stream_start"
        assert start["channel"] == "main"
        assert "message_id" in start

        delta1 = ws.receive_json()
        assert delta1["type"] == "stream_delta"
        assert delta1["content"] == "Hello "

        delta2 = ws.receive_json()
        assert delta2["type"] == "stream_delta"
        assert delta2["content"] == "world!"

        end = ws.receive_json()
        assert end["type"] == "stream_end"
        assert end["content"] == "Hello world!"
        assert end["message_id"] == start["message_id"]


@pytest.mark.asyncio
async def test_ws_message_persisted(webui_app, db_session):
    """Messages are persisted to the database."""
    from sqlalchemy import select

    from botwerk_bot.webui.models import Message

    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(AgentAssignment(user_id=user.id, agent_name="main"))
    await db_session.commit()

    async def mock_handle(agent_name, session_key, text, **kwargs):
        return ChatResult(text="Response text")

    webui_app.state.chat_service.handle_message = mock_handle

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "subscribe", "channel": "main"})
        ws.receive_json()  # subscribed

        ws.send_json({"type": "message", "channel": "main", "content": "test input"})
        ws.receive_json()  # stream_start
        ws.receive_json()  # stream_end

    # Check DB — should have 2 messages (user + assistant).
    result = await db_session.execute(
        select(Message).where(Message.user_id == user.id).order_by(Message.id)
    )
    messages = result.scalars().all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "test input"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Response text"


@pytest.mark.asyncio
async def test_ws_invalid_json(webui_app, db_session):
    """Sending invalid JSON returns an error frame."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_text("not json at all")
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "Invalid JSON" in resp["content"]


@pytest.mark.asyncio
async def test_ws_unknown_message_type(webui_app, db_session):
    """Unknown message type returns an error."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "foobar", "channel": "x"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "Unknown message type" in resp["content"]


@pytest.mark.asyncio
async def test_ws_abort(webui_app, db_session):
    """Abort message returns aborted confirmation."""
    user = User(username="testuser", password_hash="x", display_name="Test", is_admin=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(AgentAssignment(user_id=user.id, agent_name="main"))
    await db_session.commit()

    token = _make_token(user_id=user.id)
    client = TestClient(webui_app)
    with client.websocket_connect(
        "/ws/chat",
        cookies={COOKIE_NAME: token},
    ) as ws:
        ws.send_json({"type": "subscribe", "channel": "main"})
        ws.receive_json()  # subscribed

        ws.send_json({"type": "abort", "channel": "main"})
        resp = ws.receive_json()
        assert resp["type"] == "aborted"
        assert resp["channel"] == "main"
