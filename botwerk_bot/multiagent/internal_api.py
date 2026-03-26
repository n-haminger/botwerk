"""Internal localhost HTTP API bridging CLI subprocesses to the InterAgentBus and TaskHub.

CLI subprocesses (claude, codex, gemini) run as separate OS processes and
cannot access in-memory objects directly. This lightweight aiohttp server
exposes endpoints on localhost only, so tool scripts like ``ask_agent.py``,
``ask_agent_async.py``, ``create_task.py``, and ``ask_parent.py`` can
communicate with the bus and task hub.

The server also starts in **task-only mode** (no multi-agent bus) when
``tasks.enabled`` is true but no sub-agents are configured.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from botwerk_bot.multiagent.auth import AgentAuthRegistry
    from botwerk_bot.multiagent.bus import InterAgentBus
    from botwerk_bot.multiagent.health import AgentHealth
    from botwerk_bot.tasks.hub import TaskHub

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8799
_BIND_ALL_HOST = ".".join(["0"] * 4)


class InternalAgentAPI:
    """HTTP server for CLI → Bus / TaskHub communication.

    Binds to ``127.0.0.1`` by default.  When *docker_mode* is ``True`` it
    binds to ``0.0.0.0`` so that CLI processes running inside a Docker
    container can reach the API via ``host.docker.internal``.

    The *bus* parameter is optional: when ``None`` only task endpoints are
    registered (task-only mode for single-agent setups).
    """

    def __init__(
        self,
        bus: InterAgentBus | None = None,
        port: int = _DEFAULT_PORT,
        *,
        docker_mode: bool = False,
        auth_registry: AgentAuthRegistry | None = None,
    ) -> None:
        self._bus = bus
        self._port = port
        self._bind_host = _BIND_ALL_HOST if docker_mode else "127.0.0.1"
        self._health_ref: dict[str, AgentHealth] | None = None
        self._task_hub: TaskHub | None = None
        self._auth_registry = auth_registry
        self._app = web.Application()

        # Inter-agent routes (only when bus is available)
        if bus is not None:
            self._app.router.add_post("/interagent/send", self._handle_send)
            self._app.router.add_post("/interagent/send_async", self._handle_send_async)
            self._app.router.add_get("/interagent/agents", self._handle_list)
        self._app.router.add_get("/interagent/health", self._handle_health)

        # Session status routes (work with or without bus)
        self._app.router.add_get("/session/status", self._handle_session_status)
        self._app.router.add_get("/session/list", self._handle_session_list)

        # Task routes (always registered)
        self._app.router.add_post("/tasks/create", self._handle_task_create)
        self._app.router.add_post("/tasks/resume", self._handle_task_resume)
        self._app.router.add_post("/tasks/ask_parent", self._handle_task_ask_parent)
        self._app.router.add_get("/tasks/list", self._handle_task_list)
        self._app.router.add_post("/tasks/cancel", self._handle_task_cancel)
        self._app.router.add_post("/tasks/delete", self._handle_task_delete)

        self._runner: web.AppRunner | None = None

    def set_health_ref(self, health: dict[str, AgentHealth]) -> None:
        """Set reference to supervisor health dict for the /health endpoint."""
        self._health_ref = health

    def set_task_hub(self, hub: TaskHub) -> None:
        """Set the TaskHub for handling /tasks/* endpoints."""
        self._task_hub = hub

    @property
    def port(self) -> int:
        return self._port

    def _authenticate(
        self, request: web.Request, claimed_sender: str
    ) -> web.Response | str:
        """Verify Bearer token and ACL for the claimed sender.

        Returns the verified agent name (``str``) on success, or a
        ``web.Response`` error that the caller should return immediately.
        """
        if self._auth_registry is None:
            # No auth registry configured — pass through (backward compat).
            return claimed_sender

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Auth: missing/invalid Authorization header from '%s'", claimed_sender)
            return web.json_response(
                {"success": False, "error": "Missing or invalid Authorization header"},
                status=401,
            )

        token = auth_header[len("Bearer "):]
        verified = self._auth_registry.verify_token(token)
        if verified is None:
            logger.warning("Auth: invalid token from claimed sender '%s'", claimed_sender)
            return web.json_response(
                {"success": False, "error": "Invalid agent token"},
                status=401,
            )

        if verified != claimed_sender:
            logger.warning(
                "Auth: sender mismatch — token belongs to '%s', claimed '%s'",
                verified,
                claimed_sender,
            )
            return web.json_response(
                {"success": False, "error": "Sender identity mismatch"},
                status=403,
            )

        return verified

    def _authenticate_get(self, request: web.Request) -> web.Response | str | None:
        """Verify Bearer token for GET endpoints (no claimed sender in body).

        Returns the verified agent name (``str``) on success, ``None`` when
        no auth registry is configured (backward compat), or a
        ``web.Response`` error.
        """
        if self._auth_registry is None:
            return None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Auth GET: missing/invalid Authorization header")
            return web.json_response(
                {"success": False, "error": "Missing or invalid Authorization header"},
                status=401,
            )

        token = auth_header[len("Bearer "):]
        verified = self._auth_registry.verify_token(token)
        if verified is None:
            logger.warning("Auth GET: invalid token")
            return web.json_response(
                {"success": False, "error": "Invalid agent token"},
                status=401,
            )

        return verified

    def _check_acl(self, sender: str, recipient: str) -> web.Response | None:
        """Check ACL for sender→recipient. Returns error response or None."""
        if self._auth_registry is None:
            return None
        if not self._auth_registry.can_send(sender, recipient):
            logger.warning(
                "ACL: blocked %s -> %s (not permitted)", sender, recipient
            )
            reason = self._auth_registry.explain_block(sender, recipient)
            return web.json_response(
                {"success": False, "error": reason},
                status=403,
            )
        return None

    async def start(self) -> bool:
        """Start the internal API server.

        Returns:
            True when the listener is active, False when bind/start fails.
        """
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        try:
            site = web.TCPSite(self._runner, self._bind_host, self._port)
            await site.start()
        except OSError:
            logger.exception(
                "Failed to start internal agent API on port %d",
                self._port,
            )
            # Best effort cleanup so callers can safely retry/start-stop.
            await self._runner.cleanup()
            self._runner = None
            return False
        else:
            logger.info("Internal agent API listening on %s:%d", self._bind_host, self._port)
            return True

    async def stop(self) -> None:
        """Stop the internal API server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("Internal agent API stopped")

    async def _handle_send(self, request: web.Request) -> web.Response:
        """POST /interagent/send — send a message to another agent.

        Expects JSON body: ``{"from": "agent_name", "to": "agent_name", "message": "..."}``
        Returns JSON: ``{"sender": "...", "text": "...", "success": true/false, "error": "..."}``
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        sender = data.get("from", "")
        recipient = data.get("to", "")
        message = data.get("message", "")
        new_session = bool(data.get("new_session", False))

        if not recipient or not message:
            return web.json_response(
                {"success": False, "error": "Missing 'to' or 'message' field"},
                status=400,
            )

        # Authenticate sender token
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        # Check ACL
        acl_error = self._check_acl(sender, recipient)
        if acl_error is not None:
            return acl_error

        logger.debug("Auth OK: %s -> %s (send)", sender, recipient)

        assert self._bus is not None  # Routes only registered when bus is set
        result = await self._bus.send(
            sender=sender,
            recipient=recipient,
            message=message,
            new_session=new_session,
        )
        return web.json_response(asdict(result))

    async def _handle_send_async(self, request: web.Request) -> web.Response:
        """POST /interagent/send_async — fire-and-forget inter-agent message.

        Expects JSON body: ``{"from": "agent_name", "to": "agent_name", "message": "..."}``
        Returns immediately: ``{"success": true/false, "task_id": "...", "error": "..."}``
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        sender = data.get("from", "")
        recipient = data.get("to", "")
        message = data.get("message", "")
        new_session = bool(data.get("new_session", False))
        summary = str(data.get("summary", ""))
        chat_id = int(data["chat_id"]) if data.get("chat_id") else 0
        topic_id = int(data["topic_id"]) if data.get("topic_id") else None

        if not recipient or not message:
            return web.json_response(
                {"success": False, "error": "Missing 'to' or 'message' field"},
                status=400,
            )

        # Authenticate sender token
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        # Check ACL
        acl_error = self._check_acl(sender, recipient)
        if acl_error is not None:
            return acl_error

        logger.debug("Auth OK: %s -> %s (send_async)", sender, recipient)

        assert self._bus is not None  # Routes only registered when bus is set
        available = self._bus.list_agents()
        if recipient not in available:
            return web.json_response(
                {"success": False, "error": f"Agent '{recipient}' not found"},
            )

        from botwerk_bot.multiagent.bus import AsyncSendOptions

        opts = AsyncSendOptions(
            new_session=new_session,
            summary=summary,
            chat_id=chat_id,
            topic_id=topic_id,
        )
        try:
            task_id = self._bus.send_async(
                sender=sender,
                recipient=recipient,
                message=message,
                opts=opts,
            )
        except PermissionError as exc:
            return web.json_response(
                {"success": False, "error": str(exc)},
                status=403,
            )
        if task_id is None:
            return web.json_response(
                {"success": False, "error": f"Agent '{recipient}' not found"},
            )

        return web.json_response({"success": True, "task_id": task_id})

    async def _handle_list(self, request: web.Request) -> web.Response:
        """GET /interagent/agents — list all registered agents."""
        auth_result = self._authenticate_get(request)
        if isinstance(auth_result, web.Response):
            return auth_result
        assert self._bus is not None  # Routes only registered when bus is set
        return web.json_response({"agents": self._bus.list_agents()})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /interagent/health — return live health for all agents."""
        auth_result = self._authenticate_get(request)
        if isinstance(auth_result, web.Response):
            return auth_result
        if self._health_ref is None:
            return web.json_response({"agents": {}})

        agents: dict[str, dict[str, object]] = {}
        for name, health in self._health_ref.items():
            agents[name] = {
                "status": health.status,
                "uptime": health.uptime_human,
                "restart_count": health.restart_count,
                "last_crash_error": health.last_crash_error or None,
            }
        return web.json_response({"agents": agents})

    # -- Session status endpoint -------------------------------------------------

    async def _handle_session_status(self, request: web.Request) -> web.Response:
        """GET /session/status?agent=NAME&name=SESSION_NAME — query named session status.

        Returns session metadata, execution timestamps, in-flight async task
        info, and the last N transcript entries.

        Query parameters:
            agent:  Target agent whose session to inspect.
            name:   Named session name (e.g. ``ia-main``).
            tail:   Number of transcript entries to return (default 20).
        """
        auth_result = self._authenticate_get(request)
        if isinstance(auth_result, web.Response):
            return auth_result

        agent_name = request.query.get("agent", "")
        session_name = request.query.get("name", "")
        try:
            tail = int(request.query.get("tail", "20"))
        except ValueError:
            return web.json_response(
                {"success": False, "error": "'tail' must be an integer"},
                status=400,
            )

        if not agent_name or not session_name:
            return web.json_response(
                {"success": False, "error": "Missing 'agent' or 'name' query parameter"},
                status=400,
            )

        # Look up the agent's orchestrator
        if self._bus is None:
            return web.json_response(
                {"success": False, "error": "Multi-agent bus not available"},
                status=503,
            )

        stack = self._bus.get_agent(agent_name)
        if stack is None:
            return web.json_response(
                {"success": False, "error": f"Agent '{agent_name}' not found"},
                status=404,
            )

        orch = stack.bot.orchestrator
        if orch is None:
            return web.json_response(
                {"success": False, "error": f"Agent '{agent_name}' orchestrator not initialized"},
                status=503,
            )

        registry = orch.named_sessions
        ns = registry.find_by_name(session_name)

        if ns is None:
            return web.json_response(
                {
                    "success": True,
                    "found": False,
                    "agent": agent_name,
                    "session_name": session_name,
                    "error": "Session not found or ended",
                },
            )

        # Check if there's an in-flight async task for this session
        in_flight_tasks = self._bus.get_async_tasks_for_agent(agent_name)
        matching_tasks = [
            t for t in in_flight_tasks if t.get("session_name") == session_name
        ]

        # Read transcript tail
        transcript = registry.read_transcript(ns.chat_id, ns.name, tail=tail)

        result: dict[str, object] = {
            "success": True,
            "found": True,
            "agent": agent_name,
            "session_name": ns.name,
            "status": ns.status,
            "provider": ns.provider,
            "model": ns.model,
            "message_count": ns.message_count,
            "created_at": ns.created_at,
            "started_at": ns.started_at,
            "finished_at": ns.finished_at,
            "prompt_preview": ns.prompt_preview,
            "last_prompt_preview": ns.last_prompt[:200] if ns.last_prompt else "",
            "in_flight_tasks": matching_tasks,
            "transcript": transcript,
        }
        return web.json_response(result)

    async def _handle_session_list(self, request: web.Request) -> web.Response:
        """GET /session/list?agent=NAME — list all active named sessions for an agent.

        Returns a list of session summaries (no transcript content).
        """
        auth_result = self._authenticate_get(request)
        if isinstance(auth_result, web.Response):
            return auth_result

        agent_name = request.query.get("agent", "")
        if not agent_name:
            return web.json_response(
                {"success": False, "error": "Missing 'agent' query parameter"},
                status=400,
            )

        if self._bus is None:
            return web.json_response(
                {"success": False, "error": "Multi-agent bus not available"},
                status=503,
            )

        stack = self._bus.get_agent(agent_name)
        if stack is None:
            return web.json_response(
                {"success": False, "error": f"Agent '{agent_name}' not found"},
                status=404,
            )

        orch = stack.bot.orchestrator
        if orch is None:
            return web.json_response(
                {"success": False, "error": f"Agent '{agent_name}' orchestrator not initialized"},
                status=503,
            )

        registry = orch.named_sessions
        sessions: list[dict[str, object]] = [
            {
                "name": ns.name,
                "status": ns.status,
                "provider": ns.provider,
                "model": ns.model,
                "message_count": ns.message_count,
                "created_at": ns.created_at,
                "started_at": ns.started_at,
                "finished_at": ns.finished_at,
                "prompt_preview": ns.prompt_preview,
            }
            for ns in registry.list_all_active()
        ]

        # Augment with in-flight async task info
        in_flight = self._bus.get_async_tasks_for_agent(agent_name)

        return web.json_response({
            "success": True,
            "agent": agent_name,
            "sessions": sessions,
            "in_flight_async_tasks": in_flight,
        })

    # -- Task endpoints ----------------------------------------------------------

    async def _handle_task_create(self, request: web.Request) -> web.Response:
        """POST /tasks/create — create a background task.

        Expects JSON: ``{"from": "agent", "prompt": "...", "name": "...",
        "provider": null, "model": null, "thinking": null}``
        """
        if self._task_hub is None:
            return web.json_response(
                {"success": False, "error": "Task system not available"},
                status=503,
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        prompt = data.get("prompt", "")
        sender = data.get("from", "main")

        # Authenticate sender
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        if not prompt:
            return web.json_response(
                {"success": False, "error": "Missing 'prompt' field"},
                status=400,
            )

        from botwerk_bot.tasks.models import TaskSubmit

        submit = TaskSubmit(
            chat_id=data.get("chat_id", 0),
            prompt=prompt,
            message_id=0,
            thread_id=data.get("topic_id") or None,
            parent_agent=sender,
            name=data.get("name", ""),
            provider_override=data.get("provider") or "",
            model_override=data.get("model") or "",
            thinking_override=data.get("thinking") or "",
        )

        try:
            task_id = self._task_hub.submit(submit)
        except ValueError as exc:
            return web.json_response({"success": False, "error": str(exc)})

        return web.json_response({"success": True, "task_id": task_id})

    async def _handle_task_resume(self, request: web.Request) -> web.Response:
        """POST /tasks/resume — resume a completed task with a follow-up.

        Expects JSON: ``{"task_id": "...", "prompt": "...", "from": "agent"}``
        """
        if self._task_hub is None:
            return web.json_response(
                {"success": False, "error": "Task system not available"},
                status=503,
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        task_id = data.get("task_id", "")
        prompt = data.get("prompt", "")
        sender = data.get("from", "")

        # Authenticate sender
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        if not task_id or not prompt:
            return web.json_response(
                {"success": False, "error": "Missing 'task_id' or 'prompt' field"},
                status=400,
            )

        # Verify the requester owns this task
        entry = self._task_hub.registry.get(task_id)
        if entry is not None and entry.parent_agent != sender:
            return web.json_response(
                {"success": False, "error": "Not authorized to resume this task"},
                status=403,
            )

        try:
            resumed_id = self._task_hub.resume(task_id, prompt, parent_agent=sender)
        except ValueError as exc:
            return web.json_response({"success": False, "error": str(exc)})

        return web.json_response({"success": True, "task_id": resumed_id})

    async def _handle_task_ask_parent(self, request: web.Request) -> web.Response:
        """POST /tasks/ask_parent — task agent forwards a question to the parent.

        Expects JSON: ``{"task_id": "...", "question": "...", "from": "agent"}``
        Returns immediately. The parent agent will resume the task with the answer.
        """
        if self._task_hub is None:
            return web.json_response(
                {"success": False, "error": "Task system not available"},
                status=503,
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        task_id = data.get("task_id", "")
        question = data.get("question", "")
        sender = data.get("from", "")

        # Authenticate sender
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        if not task_id or not question:
            return web.json_response(
                {"success": False, "error": "Missing 'task_id' or 'question' field"},
                status=400,
            )

        result = await self._task_hub.forward_question(task_id, question)
        is_error = result.startswith("Error:")
        return web.json_response(
            {
                "success": not is_error,
                "answer": result,
                **({"error": result} if is_error else {}),
            }
        )

    async def _handle_task_list(self, request: web.Request) -> web.Response:
        """GET /tasks/list — list tasks, filtered by authenticated agent."""
        auth_result = self._authenticate_get(request)
        if isinstance(auth_result, web.Response):
            return auth_result
        if self._task_hub is None:
            return web.json_response({"tasks": []})

        # Derive filter from authenticated identity, not query parameter.
        # Privileged agents see all tasks; restricted agents see only their own.
        verified_agent = auth_result  # str or None (no auth registry)
        if verified_agent and self._auth_registry:
            trust = self._auth_registry.get_trust_level(verified_agent)
            parent_agent = None if trust == "privileged" else verified_agent
        else:
            parent_agent = request.query.get("from") or None

        entries = self._task_hub.registry.list_all(parent_agent=parent_agent)
        return web.json_response(
            {
                "tasks": [e.to_dict() for e in entries],
            }
        )

    async def _handle_task_cancel(self, request: web.Request) -> web.Response:
        """POST /tasks/cancel — cancel a running task."""
        if self._task_hub is None:
            return web.json_response(
                {"success": False, "error": "Task system not available"},
                status=503,
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        task_id = data.get("task_id", "")
        sender = data.get("from", "")

        # Authenticate sender
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        if not task_id:
            return web.json_response(
                {"success": False, "error": "Missing 'task_id' field"},
                status=400,
            )

        # Verify the requester owns this task (sender is always set when auth is active)
        if sender:
            entry = self._task_hub.registry.get(task_id)
            if entry is not None and entry.parent_agent != sender:
                return web.json_response(
                    {"success": False, "error": "Not authorized to cancel this task"},
                    status=403,
                )

        cancelled = await self._task_hub.cancel(task_id)
        return web.json_response({"success": cancelled})

    async def _handle_task_delete(self, request: web.Request) -> web.Response:
        """POST /tasks/delete — permanently delete a finished task (entry + folder)."""
        if self._task_hub is None:
            return web.json_response(
                {"success": False, "error": "Task system not available"},
                status=503,
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON body"},
                status=400,
            )

        task_id = data.get("task_id", "")
        sender = data.get("from", "")

        # Authenticate sender
        auth_result = self._authenticate(request, sender)
        if isinstance(auth_result, web.Response):
            return auth_result
        sender = auth_result

        if not task_id:
            return web.json_response(
                {"success": False, "error": "Missing 'task_id' field"},
                status=400,
            )

        entry = self._task_hub.registry.get(task_id)
        if entry is None:
            return web.json_response(
                {"success": False, "error": f"Task '{task_id}' not found"},
                status=404,
            )
        if sender and entry.parent_agent != sender:
            return web.json_response(
                {"success": False, "error": "Not authorized to delete this task"},
                status=403,
            )

        if not self._task_hub.registry.delete(task_id):
            return web.json_response(
                {"success": False, "error": "Task is still running or waiting"},
                status=409,
            )
        return web.json_response({"success": True})
