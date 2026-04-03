"""Agent management API routes (Phase 4)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from botwerk_bot.infra.json_store import atomic_json_save
from botwerk_bot.multiagent.models import SubAgentConfig
from botwerk_bot.webui.database import get_db
from botwerk_bot.webui.linux_users import create_linux_user, user_exists
from botwerk_bot.webui.models import AgentAssignment
from botwerk_bot.webui.permission_templates import apply_template, get_template, get_templates
from botwerk_bot.webui.schemas import (
    AgentCreate,
    AgentHierarchyNode,
    AgentHierarchyResponse,
    AgentResponse,
    AgentUpdate,
    PermissionTemplateResponse,
    TokenPayload,
)

logger = logging.getLogger(__name__)

# Default agents.json path — can be overridden via app.state.agents_json_path
_DEFAULT_AGENTS_PATH = Path.home() / ".botwerk" / "agents.json"


def _get_agents_path() -> Path:
    """Return the path to agents.json."""
    return _DEFAULT_AGENTS_PATH


def _load_agents_raw(path: Path) -> list[dict]:
    """Load agents.json as raw dicts."""
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Cannot read agents.json at %s", path)
        return []
    if not isinstance(raw, list):
        return []
    return raw


def _save_agents_raw(path: Path, data: list[dict]) -> None:
    """Save agents.json atomically."""
    atomic_json_save(path, data)


def _agent_to_response(raw: dict, status_map: dict[str, str] | None = None) -> AgentResponse:
    """Convert a raw agent dict to an AgentResponse."""
    agent_status = "stopped"
    if status_map and raw.get("name") in status_map:
        agent_status = status_map[raw["name"]]

    return AgentResponse(
        name=raw.get("name", ""),
        provider=raw.get("provider"),
        model=raw.get("model"),
        agent_type=raw.get("agent_type", "worker"),
        linux_user=bool(raw.get("linux_user", False)),
        trust_level=raw.get("trust_level", "restricted"),
        can_contact=raw.get("can_contact", []),
        accept_from=raw.get("accept_from", []),
        status=agent_status,
        manager=raw.get("manager"),
        workers=raw.get("workers", []),
    )


def create_agent_router(auth_dep: object) -> APIRouter:
    """Build and return the agent router."""
    router = APIRouter(prefix="/agents", tags=["agents"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    # -- List agents -----------------------------------------------------------

    @router.get("")
    async def list_agents(
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> list[AgentResponse]:
        """List agents. Admins see all; normal users see only assigned agents."""
        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        if token.is_admin:
            return [_agent_to_response(a) for a in all_agents]

        # Non-admin: filter to assigned agents
        result = await db.execute(
            select(AgentAssignment.agent_name).where(
                AgentAssignment.user_id == token.user_id,
            )
        )
        assigned_names = {row[0] for row in result.all()}
        return [
            _agent_to_response(a)
            for a in all_agents
            if a.get("name") in assigned_names
        ]

    # -- Get single agent ------------------------------------------------------

    @router.get("/{name}")
    async def get_agent(
        name: str,
        token: TokenPayload = Depends(auth_dep),
        db: AsyncSession = Depends(get_db),
    ) -> AgentResponse:
        """Get a single agent by name."""
        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)
        match = next((a for a in all_agents if a.get("name") == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        if not token.is_admin:
            result = await db.execute(
                select(AgentAssignment.agent_name).where(
                    AgentAssignment.user_id == token.user_id,
                    AgentAssignment.agent_name == name,
                )
            )
            if result.first() is None:
                raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        return _agent_to_response(match)

    # -- Create agent ----------------------------------------------------------

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_agent(
        body: AgentCreate,
        token: TokenPayload = Depends(auth_dep),
    ) -> AgentResponse:
        """Create a new agent (admin only)."""
        _require_admin(token)

        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        if any(a.get("name") == body.name for a in all_agents):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent '{body.name}' already exists",
            )

        if body.name == "main":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create agent named 'main' (reserved)",
            )

        # Handle Linux user provisioning
        if body.linux_user and body.linux_user_name:
            if not user_exists(body.linux_user_name):
                template = get_template(body.permission_template or "restricted")
                groups = template.groups if template else []
                sudo_rules = template.sudo_rules if template else []
                created = create_linux_user(
                    body.linux_user_name,
                    groups=groups,
                    sudo_rules=sudo_rules,
                )
                if not created:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to create Linux user '{body.linux_user_name}'",
                    )
            elif body.permission_template:
                apply_template(body.linux_user_name, body.permission_template)

        # Build agent config dict
        new_agent: dict = {
            "name": body.name,
        }
        if body.provider:
            new_agent["provider"] = body.provider
        if body.model:
            new_agent["model"] = body.model
        if body.linux_user:
            new_agent["linux_user"] = True
        new_agent["agent_type"] = body.agent_type
        new_agent["trust_level"] = body.trust_level
        if body.can_contact:
            new_agent["can_contact"] = body.can_contact
        if body.accept_from:
            new_agent["accept_from"] = body.accept_from

        # Generate a secret via SubAgentConfig default_factory
        cfg = SubAgentConfig(name=body.name)
        new_agent["agent_secret"] = cfg.agent_secret

        all_agents.append(new_agent)
        _save_agents_raw(agents_path, all_agents)

        return _agent_to_response(new_agent)

    # -- Update agent ----------------------------------------------------------

    @router.put("/{name}")
    async def update_agent(
        name: str,
        body: AgentUpdate,
        token: TokenPayload = Depends(auth_dep),
    ) -> AgentResponse:
        """Update an agent's config (admin only)."""
        _require_admin(token)

        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        idx = next((i for i, a in enumerate(all_agents) if a.get("name") == name), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        agent = all_agents[idx]
        updates = body.model_dump(exclude_none=True)

        # Handle permission template application
        if "permission_template" in updates:
            linux_user_name = updates.pop("permission_template")
            target_user = agent.get("linux_user_name") or f"botwerk-{name}"
            if user_exists(target_user):
                apply_template(target_user, linux_user_name)

        # Apply field updates
        for key, value in updates.items():
            agent[key] = value

        all_agents[idx] = agent
        _save_agents_raw(agents_path, all_agents)

        return _agent_to_response(agent)

    # -- Delete agent ----------------------------------------------------------

    @router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_agent(
        name: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> None:
        """Remove an agent (admin only). Does NOT delete the Linux user."""
        _require_admin(token)

        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        original_len = len(all_agents)
        all_agents = [a for a in all_agents if a.get("name") != name]

        if len(all_agents) == original_len:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        _save_agents_raw(agents_path, all_agents)

    # -- Start / Stop (placeholders) -------------------------------------------

    @router.post("/{name}/start")
    async def start_agent(
        name: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict[str, str]:
        """Start an agent (admin only). Placeholder."""
        _require_admin(token)
        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)
        if not any(a.get("name") == name for a in all_agents):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {"status": "start_requested", "agent": name}

    @router.post("/{name}/stop")
    async def stop_agent(
        name: str,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict[str, str]:
        """Stop an agent (admin only). Placeholder."""
        _require_admin(token)
        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)
        if not any(a.get("name") == name for a in all_agents):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {"status": "stop_requested", "agent": name}

    # -- Hierarchy -------------------------------------------------------------

    @router.put("/{name}/hierarchy")
    async def set_hierarchy(
        name: str,
        body: AgentUpdate,
        token: TokenPayload = Depends(auth_dep),
    ) -> AgentResponse:
        """Set manager/workers for an agent (admin only)."""
        _require_admin(token)

        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        idx = next((i for i, a in enumerate(all_agents) if a.get("name") == name), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        agent = all_agents[idx]
        if body.manager is not None:
            agent["manager"] = body.manager
        if body.workers is not None:
            agent["workers"] = body.workers

        all_agents[idx] = agent
        _save_agents_raw(agents_path, all_agents)

        return _agent_to_response(agent)

    @router.get("/hierarchy/tree")
    async def get_hierarchy(
        token: TokenPayload = Depends(auth_dep),
    ) -> AgentHierarchyResponse:
        """Return the full agent hierarchy as a tree."""
        _require_admin(token)

        agents_path = _get_agents_path()
        all_agents = _load_agents_raw(agents_path)

        # Build lookup
        by_name: dict[str, dict] = {a["name"]: a for a in all_agents if "name" in a}
        children_of: dict[str, list[str]] = {}
        has_manager: set[str] = set()

        for a in all_agents:
            name = a.get("name", "")
            workers = a.get("workers", [])
            children_of[name] = workers
            for w in workers:
                has_manager.add(w)

        def _build_node(agent_name: str) -> AgentHierarchyNode:
            a = by_name.get(agent_name, {"name": agent_name})
            child_names = children_of.get(agent_name, [])
            return AgentHierarchyNode(
                name=agent_name,
                agent_type=a.get("agent_type", "worker"),
                status="unknown",
                workers=[_build_node(c) for c in child_names if c in by_name],
            )

        roots = [
            _build_node(a["name"])
            for a in all_agents
            if a.get("name") and a["name"] not in has_manager
        ]

        return AgentHierarchyResponse(roots=roots)

    # -- Permission templates --------------------------------------------------

    @router.get("/templates/list")
    async def list_templates(
        token: TokenPayload = Depends(auth_dep),
    ) -> list[PermissionTemplateResponse]:
        """List available permission templates."""
        _require_admin(token)
        return [
            PermissionTemplateResponse(
                name=t.name,
                description=t.description,
                groups=t.groups,
                sudo_rules=t.sudo_rules,
            )
            for t in get_templates()
        ]

    return router
