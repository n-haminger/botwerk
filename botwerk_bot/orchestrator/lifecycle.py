"""Orchestrator lifecycle: async factory, startup, shutdown, infra management."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from typing import TYPE_CHECKING

from botwerk_bot.files.allowed_roots import resolve_allowed_roots
from botwerk_bot.workspace.init import inject_runtime_environment
from botwerk_bot.workspace.paths import BotwerkPaths, resolve_paths
from botwerk_bot.workspace.skill_sync import cleanup_botwerk_links

if TYPE_CHECKING:
    from botwerk_bot.config import AgentConfig
    from botwerk_bot.orchestrator.core import Orchestrator

logger = logging.getLogger(__name__)


async def create_orchestrator(
    config: AgentConfig,
    *,
    agent_name: str = "main",
) -> Orchestrator:
    """Async factory: build an Orchestrator.

    Workspace must already be initialized by the caller (``__main__.load_config``).
    """
    from botwerk_bot.orchestrator.core import Orchestrator

    paths = resolve_paths(botwerk_home=config.botwerk_home)

    # Only set the process-wide env var for the main agent to avoid
    # race conditions in multi-agent mode (sub-agents use per-subprocess env).
    if agent_name == "main":
        os.environ["BOTWERK_HOME"] = str(paths.botwerk_home)

    await asyncio.to_thread(
        inject_runtime_environment,
        paths,
        agent_name=agent_name,
        transport="webui",
    )

    orch = Orchestrator(
        config,
        paths,
        agent_name=agent_name,
        interagent_port=config.interagent_port,
        agent_secret=config.agent_secret,
    )

    from botwerk_bot.cli.auth import AuthStatus, check_all_auth

    auth_results = await asyncio.to_thread(check_all_auth)
    orch._providers.apply_auth_results(
        auth_results,
        auth_status_enum=AuthStatus,
        cli_service=orch._cli_service,
    )

    if not orch._providers.available_providers:
        logger.error("No authenticated providers found! CLI calls will fail.")
    else:
        logger.info(
            "Available providers: %s",
            ", ".join(sorted(orch._providers.available_providers)),
        )

    await asyncio.to_thread(orch._providers.init_gemini_state, paths.workspace)

    codex_cache = await orch._observers.init_model_caches(
        on_gemini_refresh=orch._providers.on_gemini_models_refresh
    )
    orch._observers.init_task_observers(
        cron_manager=orch._cron_manager,
        webhook_manager=orch._webhook_manager,
        cli_service=orch._cli_service,
        codex_cache=codex_cache,
    )
    orch._providers._codex_cache_fn = lambda: orch._observers.codex_cache
    await orch._observers.start_all()

    # Direct API server (WebSocket, designed for Tailscale)
    if config.api.enabled:
        await start_api_server(orch, config, paths)

    await orch._observers.start_config_reloader(
        on_hot_reload=orch._on_config_hot_reload,
        on_restart_needed=lambda fields: logger.warning(
            "Config changed but requires restart: %s", ", ".join(fields)
        ),
    )

    return orch


async def start_api_server(
    orch: Orchestrator,
    config: AgentConfig,
    paths: BotwerkPaths,
) -> None:
    """Initialize and start the direct WebSocket API server."""
    try:
        from botwerk_bot.api.server import ApiServer
    except ImportError:
        logger.warning(
            "API server enabled but PyNaCl is not installed. Install with: pip install botwerk[api]"
        )
        return

    if not config.api.token:
        from botwerk_bot.config import update_config_file_async

        token = secrets.token_urlsafe(32)
        config.api.token = token
        await update_config_file_async(
            paths.config_path,
            api={**config.api.model_dump(), "token": token},
        )
        logger.info("Generated API auth token (persisted to config)")

    default_chat_id = config.api.chat_id or 1
    server = ApiServer(config.api, default_chat_id=default_chat_id)
    server.set_message_handler(orch.handle_message_streaming)
    server.set_abort_handler(orch.abort)
    server.set_file_context(
        allowed_roots=resolve_allowed_roots(config.file_access, paths.workspace),
        upload_dir=paths.api_files_dir,
        workspace=paths.workspace,
    )
    server.set_provider_info(orch._providers.build_provider_info(orch._observers.codex_cache_obs))
    server.set_active_state_getter(
        lambda: orch._providers.resolve_runtime_target(orch._config.model)
    )

    try:
        await server.start()
    except OSError:
        logger.exception(
            "Failed to start API server on %s:%d",
            config.api.host,
            config.api.port,
        )
        return

    orch._api_stop = server.stop
    orch._api_clear_buffer = server.clear_buffer


async def shutdown(orch: Orchestrator) -> None:
    """Cleanup on bot shutdown."""
    killed = await orch._process_registry.kill_all_active()
    if killed:
        logger.info("Shutdown terminated %d active CLI process(es)", killed)
    if orch._api_stop is not None:
        await orch._api_stop()
    await asyncio.to_thread(cleanup_botwerk_links, orch._paths)
    await orch._observers.stop_all()
    logger.info("Orchestrator shutdown")
