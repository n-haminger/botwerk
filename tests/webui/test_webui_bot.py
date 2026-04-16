"""Tests for the WebUIBot transport and its ChatService wiring."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botwerk_bot.bot.protocol import BotProtocol
from botwerk_bot.bot.webui_bot import WebUIBot, create_webui_bot
from botwerk_bot.webui.chat_service import (
    ChatResult,
    get_chat_service,
    reset_chat_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a fresh ChatService singleton."""
    reset_chat_service()
    yield
    reset_chat_service()


def _make_bot(name: str = "main") -> WebUIBot:
    config = MagicMock()
    return WebUIBot(config, agent_name=name)


def test_webui_bot_satisfies_protocol():
    bot = _make_bot()
    assert isinstance(bot, BotProtocol)


def test_create_webui_bot_factory_returns_webui_bot():
    config = MagicMock()
    bot = create_webui_bot(config, agent_name="worker")
    assert isinstance(bot, WebUIBot)
    assert bot.config is config


def test_transport_registry_default_factory_is_webui():
    from botwerk_bot import transport_registry

    transport_registry.clear_transports()
    config = MagicMock()
    bot = transport_registry.create_bot(config, agent_name="worker")
    assert isinstance(bot, WebUIBot)


@pytest.mark.asyncio
async def test_run_registers_with_chat_service_and_blocks_until_shutdown():
    """run() must register agent, await shutdown, unregister on exit."""
    bot = _make_bot("alpha")
    fake_orch = MagicMock()
    fake_orch.shutdown = AsyncMock()

    with patch(
        "botwerk_bot.bot.webui_bot.Orchestrator.create",
        new=AsyncMock(return_value=fake_orch),
    ):
        run_task = asyncio.create_task(bot.run())

        # Give run() a chance to register before we assert.
        for _ in range(50):
            await asyncio.sleep(0.01)
            if get_chat_service().has_agent("alpha"):
                break

        assert get_chat_service().has_agent("alpha")
        assert bot.orchestrator is fake_orch

        # run() must still be blocking.
        assert not run_task.done()

        await bot.shutdown()
        exit_code = await asyncio.wait_for(run_task, timeout=1.0)
        assert exit_code == 0
        assert not get_chat_service().has_agent("alpha")
        fake_orch.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_executes_startup_hooks_after_registration():
    bot = _make_bot("beta")
    fake_orch = MagicMock()
    fake_orch.shutdown = AsyncMock()
    hook_saw_registration = False

    async def _hook() -> None:
        nonlocal hook_saw_registration
        hook_saw_registration = get_chat_service().has_agent("beta")

    bot.register_startup_hook(_hook)

    with patch(
        "botwerk_bot.bot.webui_bot.Orchestrator.create",
        new=AsyncMock(return_value=fake_orch),
    ):
        run_task = asyncio.create_task(bot.run())
        # Wait for hook to execute.
        for _ in range(50):
            await asyncio.sleep(0.01)
            if hook_saw_registration:
                break
        await bot.shutdown()
        await asyncio.wait_for(run_task, timeout=1.0)

    assert hook_saw_registration, "startup hook must run AFTER ChatService registration"


@pytest.mark.asyncio
async def test_chat_service_end_to_end_routes_to_orchestrator():
    """Registered agent's orchestrator is called through ChatService.handle_message."""
    from botwerk_bot.orchestrator.core import OrchestratorResult
    from botwerk_bot.session import SessionKey

    bot = _make_bot("gamma")
    fake_orch = MagicMock()
    fake_orch.shutdown = AsyncMock()
    fake_orch.handle_message_streaming = AsyncMock(
        return_value=OrchestratorResult(text="hello from gamma")
    )

    with patch(
        "botwerk_bot.bot.webui_bot.Orchestrator.create",
        new=AsyncMock(return_value=fake_orch),
    ):
        run_task = asyncio.create_task(bot.run())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if get_chat_service().has_agent("gamma"):
                break

        result: ChatResult = await get_chat_service().handle_message(
            agent_name="gamma",
            session_key=SessionKey(chat_id=1),
            text="ping",
        )
        assert result.text == "hello from gamma"
        assert not result.error
        fake_orch.handle_message_streaming.assert_awaited_once()

        await bot.shutdown()
        await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_shutdown_without_run_is_safe():
    bot = _make_bot("delta")
    # shutdown() before run() should not raise.
    await bot.shutdown()
    assert not get_chat_service().has_agent("delta")


def test_notification_service_is_not_none():
    bot = _make_bot()
    assert bot.notification_service is not None
    # Implements the protocol — both methods are async.
    assert hasattr(bot.notification_service, "notify")
    assert hasattr(bot.notification_service, "notify_all")


def test_get_chat_service_returns_singleton():
    a = get_chat_service()
    b = get_chat_service()
    assert a is b
