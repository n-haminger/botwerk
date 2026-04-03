"""WebSocket handler for real-time chat with agents."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from botwerk_bot.bus.lock_pool import LockPool
from botwerk_bot.files.tags import extract_file_paths, is_image_path
from botwerk_bot.session import SessionKey
from botwerk_bot.webui.auth import COOKIE_NAME, decode_token
from botwerk_bot.webui.chat_service import ChatService
from botwerk_bot.webui.models import AgentAssignment, Message
from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)


class ChatWebSocket:
    """Manages a single WebSocket connection with channel multiplexing.

    Each client can subscribe to multiple agent channels and send messages
    to any subscribed channel.  A per-channel lock prevents concurrent
    messages to the same agent from the same user.
    """

    def __init__(
        self,
        chat_service: ChatService,
        session_factory: async_sessionmaker[AsyncSession],
        secret_key: str,
        lock_pool: LockPool,
    ) -> None:
        self._chat_service = chat_service
        self._session_factory = session_factory
        self._secret = secret_key
        self._lock_pool = lock_pool

    async def handle(self, websocket: WebSocket) -> None:
        """Full lifecycle: authenticate, listen, dispatch, close."""
        token = self._authenticate(websocket)
        if token is None:
            await websocket.close(code=4001, reason="Authentication required")
            return

        await websocket.accept()

        subscribed: set[str] = set()
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send(websocket, {
                        "type": "error",
                        "channel": "",
                        "content": "Invalid JSON",
                    })
                    continue

                msg_type = msg.get("type")
                channel = msg.get("channel", "")
                if not isinstance(channel, str) or len(channel) > 64:
                    await self._send(websocket, {
                        "type": "error",
                        "channel": "",
                        "content": "Invalid channel name",
                    })
                    continue

                if msg_type == "subscribe":
                    ok = await self._check_access(token.user_id, channel)
                    if ok:
                        subscribed.add(channel)
                        await self._send(websocket, {
                            "type": "subscribed",
                            "channel": channel,
                        })
                    else:
                        await self._send(websocket, {
                            "type": "error",
                            "channel": channel,
                            "content": "Access denied",
                        })

                elif msg_type == "message":
                    if channel not in subscribed:
                        await self._send(websocket, {
                            "type": "error",
                            "channel": channel,
                            "content": "Not subscribed to this channel",
                        })
                        continue
                    content = msg.get("content", "").strip()
                    if not content:
                        continue
                    if len(content) > 100_000:
                        await self._send(websocket, {
                            "type": "error",
                            "channel": channel,
                            "content": "Message too long (max 100,000 characters)",
                        })
                        continue
                    await self._handle_chat_message(
                        websocket, token, channel, content,
                    )

                elif msg_type == "abort":
                    if channel in subscribed:
                        # Use user_id as chat_id for WebUI sessions.
                        await self._chat_service.abort(channel, token.user_id)
                        await self._send(websocket, {
                            "type": "aborted",
                            "channel": channel,
                        })

                else:
                    await self._send(websocket, {
                        "type": "error",
                        "channel": channel,
                        "content": f"Unknown message type: {msg_type}",
                    })

        except WebSocketDisconnect:
            logger.debug("WebSocket disconnected: user_id=%d", token.user_id)
        except Exception:
            logger.exception("WebSocket error: user_id=%d", token.user_id)
            try:
                await websocket.close(code=1011, reason="Internal error")
            except Exception:  # noqa: BLE001
                pass

    # -- Authentication --------------------------------------------------------

    def _authenticate(self, websocket: WebSocket) -> TokenPayload | None:
        """Read the JWT from the cookie header. Returns None on failure."""
        token_value = websocket.cookies.get(COOKIE_NAME)
        if not token_value:
            return None
        try:
            return decode_token(token_value, self._secret)
        except Exception:  # noqa: BLE001
            return None

    # -- Access check ----------------------------------------------------------

    async def _check_access(self, user_id: int, agent_name: str) -> bool:
        """Verify that the user has an AgentAssignment for this agent."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(AgentAssignment).where(
                    AgentAssignment.user_id == user_id,
                    AgentAssignment.agent_name == agent_name,
                )
            )
            return result.scalar_one_or_none() is not None

    # -- Message handling ------------------------------------------------------

    async def _handle_chat_message(
        self,
        websocket: WebSocket,
        token: TokenPayload,
        channel: str,
        content: str,
    ) -> None:
        """Process a user chat message: persist, stream, persist response."""
        # Per-channel lock prevents concurrent messages to the same agent.
        lock_key = (token.user_id, hash(channel) % (2**31))
        lock = self._lock_pool.get(lock_key)

        if lock.locked():
            await self._send(websocket, {
                "type": "error",
                "channel": channel,
                "content": "A message is already being processed for this agent",
            })
            return

        async with lock:
            message_id = str(uuid.uuid4())

            # Persist user message.
            await self._persist_message(
                user_id=token.user_id,
                agent_name=channel,
                role="user",
                content=content,
            )

            # Notify stream start.
            await self._send(websocket, {
                "type": "stream_start",
                "channel": channel,
                "message_id": message_id,
            })

            # Build streaming callbacks.
            full_response_parts: list[str] = []

            async def on_text_delta(delta: str) -> None:
                full_response_parts.append(delta)
                await self._send(websocket, {
                    "type": "stream_delta",
                    "channel": channel,
                    "content": delta,
                })

            async def on_tool_activity(tool_name: str) -> None:
                await self._send(websocket, {
                    "type": "tool_activity",
                    "channel": channel,
                    "content": tool_name,
                })

            async def on_system_status(status: str | None) -> None:
                await self._send(websocket, {
                    "type": "system_status",
                    "channel": channel,
                    "content": status or "",
                })

            # Call orchestrator via ChatService.
            session_key = SessionKey(chat_id=token.user_id)
            result = await self._chat_service.handle_message(
                agent_name=channel,
                session_key=session_key,
                text=content,
                on_text_delta=on_text_delta,
                on_tool_activity=on_tool_activity,
                on_system_status=on_system_status,
            )

            # The final text is either from streaming deltas or the result.
            final_text = result.text if result.text else "".join(full_response_parts)

            # Persist assistant response.
            await self._persist_message(
                user_id=token.user_id,
                agent_name=channel,
                role="assistant",
                content=final_text,
            )

            # Detect <file:...> tags in the response and build file metadata.
            file_paths = extract_file_paths(final_text)
            files_meta: list[dict[str, object]] = []
            for fp in file_paths:
                from pathlib import Path as _Path

                p = _Path(fp)
                files_meta.append({
                    "name": p.name,
                    "path": fp,
                    "is_image": is_image_path(fp),
                })

            # Send stream_end.
            end_payload: dict[str, object] = {
                "type": "stream_end",
                "channel": channel,
                "message_id": message_id,
                "content": final_text,
            }
            if files_meta:
                end_payload["files"] = files_meta
            await self._send(websocket, end_payload)

    # -- Persistence -----------------------------------------------------------

    async def _persist_message(
        self,
        *,
        user_id: int,
        agent_name: str,
        role: str,
        content: str,
    ) -> Message:
        """Store a message in the database and return it."""
        async with self._session_factory() as db:
            msg = Message(
                user_id=user_id,
                agent_name=agent_name,
                role=role,
                content=content,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            return msg

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    async def _send(websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send a JSON message, silently ignoring closed connections."""
        try:
            await websocket.send_json(data)
        except Exception:  # noqa: BLE001
            pass
