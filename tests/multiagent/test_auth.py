"""Tests for multiagent/auth.py: AgentAuthRegistry, ACL enforcement, and auth integration.

Covers:
- AgentAuthRegistry token verification and ACL checks
- InterAgentBus ACL integration
- InternalAgentAPI authentication and authorization
- SubAgentConfig security defaults
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from botwerk_bot.multiagent.auth import AgentACL, AgentAuthRegistry
from botwerk_bot.multiagent.bus import InterAgentBus
from botwerk_bot.multiagent.internal_api import InternalAgentAPI
from botwerk_bot.multiagent.models import SubAgentConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    name: str,
    secret: str = "",
    trust_level: str = "restricted",
    can_contact: list[str] | None = None,
    accept_from: list[str] | None = None,
) -> SubAgentConfig:
    """Create a SubAgentConfig with security fields."""
    return SubAgentConfig(
        name=name,
        agent_secret=secret,
        trust_level=trust_level,
        can_contact=can_contact or [],
        accept_from=accept_from or ["main"],
    )


def _make_stack(response: str = "ok") -> MagicMock:
    """Create a mock AgentStack with a working orchestrator."""
    stack = MagicMock()
    orch = MagicMock()
    orch.handle_interagent_message = AsyncMock(
        return_value=(response, "ia-sender", ""),
    )
    stack.bot.orchestrator = orch
    return stack


# ===========================================================================
# AgentAuthRegistry
# ===========================================================================


class TestRegistryReload:
    """Test reload() builds correct token map and ACLs."""

    def test_reload_builds_token_map(self) -> None:
        reg = AgentAuthRegistry()
        agents = [_make_agent("alpha", secret="secret-alpha")]
        reg.reload(agents, main_agent_secret="secret-main")

        assert reg.verify_token("secret-main") == "main"
        assert reg.verify_token("secret-alpha") == "alpha"

    def test_reload_builds_acls_for_all_agents(self) -> None:
        reg = AgentAuthRegistry()
        agents = [
            _make_agent("a", secret="sa"),
            _make_agent("b", secret="sb"),
        ]
        reg.reload(agents, main_agent_secret="sm")

        # main + 2 sub-agents = 3 ACL entries
        assert reg.get_trust_level("main") == "privileged"
        assert reg.get_trust_level("a") == "restricted"
        assert reg.get_trust_level("b") == "restricted"

    def test_reload_clears_old_entries(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("old", secret="old-secret")], main_agent_secret="ms")
        assert reg.verify_token("old-secret") == "old"

        # Reload with different agents
        reg.reload([_make_agent("new", secret="new-secret")], main_agent_secret="ms")
        assert reg.verify_token("old-secret") is None
        assert reg.verify_token("new-secret") == "new"

    def test_reload_without_main_secret(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("a", secret="sa")])
        # main has no token registered
        assert reg.verify_token("") is None
        # but main still has privileged ACL
        assert reg.get_trust_level("main") == "privileged"

    def test_agent_without_secret_not_in_token_map(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("nosecret", secret="")])
        # No token -> not verifiable, but ACL still exists
        assert reg.get_trust_level("nosecret") == "restricted"


class TestVerifyToken:
    """Test verify_token() behavior."""

    def test_valid_token_returns_agent_name(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("bot", secret="tok123")], main_agent_secret="main-tok")

        assert reg.verify_token("tok123") == "bot"
        assert reg.verify_token("main-tok") == "main"

    def test_invalid_token_returns_none(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("bot", secret="real")])

        assert reg.verify_token("fake") is None
        assert reg.verify_token("") is None

    def test_empty_registry_returns_none(self) -> None:
        reg = AgentAuthRegistry()
        assert reg.verify_token("anything") is None


class TestCanSend:
    """Test can_send() ACL enforcement."""

    def test_privileged_agent_can_contact_anyone(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload(
            [_make_agent("sub", secret="s", accept_from=["main"])],
            main_agent_secret="m",
        )
        # main is privileged with can_contact=["*"]
        assert reg.can_send("main", "sub") is True

    def test_restricted_agent_blocked_from_unauthorized_target(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("a", secret="sa", can_contact=["b"], accept_from=["main"]),
            _make_agent("b", secret="sb", can_contact=[], accept_from=["main"]),
        ])
        # a can contact b, but b's accept_from does not include a
        assert reg.can_send("a", "b") is False

    def test_allowed_when_both_sides_permit(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("a", secret="sa", can_contact=["b"]),
            _make_agent("b", secret="sb", accept_from=["a", "main"]),
        ])
        assert reg.can_send("a", "b") is True

    def test_main_always_privileged(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("sub", secret="s")])
        assert reg.get_trust_level("main") == "privileged"
        assert reg.can_send("main", "sub") is True

    def test_main_implicitly_in_accept_from(self) -> None:
        """Main is added to accept_from even if not listed explicitly."""
        reg = AgentAuthRegistry()
        # accept_from only lists "other", not "main"
        reg.reload([_make_agent("sub", secret="s", accept_from=["other"])])
        # main should still be able to contact sub
        assert reg.can_send("main", "sub") is True

    def test_wildcard_can_contact(self) -> None:
        """Agent with can_contact=["*"] can reach any recipient that accepts."""
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("sender", secret="ss", can_contact=["*"]),
            _make_agent("target", secret="st", accept_from=["sender"]),
        ])
        assert reg.can_send("sender", "target") is True

    def test_wildcard_accept_from(self) -> None:
        """Agent with accept_from=["*"] accepts messages from anyone."""
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("sender", secret="ss", can_contact=["target"]),
            _make_agent("target", secret="st", accept_from=["*"]),
        ])
        assert reg.can_send("sender", "target") is True

    def test_unknown_sender_denied(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("sub", secret="s")])
        assert reg.can_send("nonexistent", "sub") is False

    def test_unknown_recipient_blocked(self) -> None:
        """Unknown recipient is blocked by ACL (fail-closed)."""
        reg = AgentAuthRegistry()
        reg.reload([], main_agent_secret="m")
        assert reg.can_send("main", "ghost") is False

    def test_sender_not_in_recipients_accept_from(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("a", secret="sa", can_contact=["b"]),
            _make_agent("b", secret="sb", accept_from=[]),  # empty, but main gets added
        ])
        # a can_contact b, but b only accepts from main (implicitly added)
        assert reg.can_send("a", "b") is False

    def test_bidirectional_contact(self) -> None:
        """Two agents that mutually list each other can communicate both ways."""
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("a", secret="sa", can_contact=["b"], accept_from=["b"]),
            _make_agent("b", secret="sb", can_contact=["a"], accept_from=["a"]),
        ])
        assert reg.can_send("a", "b") is True
        assert reg.can_send("b", "a") is True


class TestGetTrustLevel:
    """Test get_trust_level() behavior."""

    def test_main_is_privileged(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([])
        assert reg.get_trust_level("main") == "privileged"

    def test_sub_default_restricted(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("sub", trust_level="restricted")])
        assert reg.get_trust_level("sub") == "restricted"

    def test_sub_privileged_when_set(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([_make_agent("admin", trust_level="privileged")])
        assert reg.get_trust_level("admin") == "privileged"

    def test_unknown_agent_returns_restricted(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([])
        assert reg.get_trust_level("unknown") == "restricted"


# ===========================================================================
# Linux user isolation
# ===========================================================================


class TestLinuxUserIsolation:
    """Agents with linux_user=True are fully isolated regardless of config."""

    def test_linux_user_agent_cannot_contact_anyone(self) -> None:
        reg = AgentAuthRegistry()
        isolated = SubAgentConfig(
            name="iso",
            agent_secret="s-iso",
            linux_user=True,
            can_contact=["*"],  # Explicitly set -- should be overridden
        )
        peer = SubAgentConfig(name="peer", agent_secret="s-peer")
        reg.reload([isolated, peer])
        assert reg.can_send("iso", "peer") is False
        assert reg.can_send("iso", "main") is False

    def test_linux_user_agent_accepts_from_main_only(self) -> None:
        reg = AgentAuthRegistry()
        isolated = SubAgentConfig(
            name="iso",
            agent_secret="s-iso",
            linux_user=True,
            accept_from=["*"],  # Explicitly set -- should be overridden
        )
        peer = SubAgentConfig(name="peer", agent_secret="s-peer")
        reg.reload([isolated, peer])
        assert reg.can_send("main", "iso") is True
        assert reg.can_send("peer", "iso") is False

    def test_normal_agent_can_contact_peers(self) -> None:
        """Normal agents (linux_user=False) get open defaults."""
        reg = AgentAuthRegistry()
        a = SubAgentConfig(name="a", agent_secret="sa")
        b = SubAgentConfig(name="b", agent_secret="sb")
        reg.reload([a, b])
        assert reg.can_send("a", "b") is True
        assert reg.can_send("b", "a") is True

    def test_normal_agent_default_accepts_all(self) -> None:
        reg = AgentAuthRegistry()
        a = SubAgentConfig(name="a", agent_secret="sa")
        reg.reload([a])
        assert reg.can_send("main", "a") is True


class TestExplainBlock:
    """Test explain_block() returns informative messages."""

    def test_unknown_sender(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([])
        msg = reg.explain_block("ghost", "main")
        assert "not registered" in msg

    def test_can_contact_denied(self) -> None:
        """Isolated agent (linux_user) has empty can_contact enforced."""
        reg = AgentAuthRegistry()
        isolated = SubAgentConfig(
            name="iso", agent_secret="s", linux_user=True,
        )
        reg.reload([isolated])
        msg = reg.explain_block("iso", "main")
        assert "can_contact" in msg

    def test_accept_from_denied(self) -> None:
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("a", secret="sa", can_contact=["b"]),
            _make_agent("b", secret="sb", accept_from=[]),
        ])
        msg = reg.explain_block("a", "b")
        assert "accept_from" in msg


# ===========================================================================
# InterAgentBus ACL integration
# ===========================================================================


class TestBusACL:
    """Test that InterAgentBus enforces ACL via auth_registry."""

    def _setup_bus(self) -> tuple[InterAgentBus, AgentAuthRegistry]:
        reg = AgentAuthRegistry()
        reg.reload([
            _make_agent("allowed", secret="sa", can_contact=["target"], accept_from=["main"]),
            _make_agent("blocked", secret="sb", can_contact=[], accept_from=["main"]),
            _make_agent("target", secret="st", accept_from=["allowed", "main"]),
        ], main_agent_secret="ms")
        bus = InterAgentBus(auth_registry=reg)
        bus.register("target", _make_stack("hello"))
        bus.register("allowed", _make_stack())
        bus.register("blocked", _make_stack())
        return bus, reg

    async def test_send_blocked_by_acl(self) -> None:
        bus, _ = self._setup_bus()
        result = await bus.send("blocked", "target", "hi")
        assert result.success is False
        assert "blocked" in result.error

    async def test_send_allowed_by_acl(self) -> None:
        bus, _ = self._setup_bus()
        result = await bus.send("allowed", "target", "hi")
        assert result.success is True
        assert result.text == "hello"

    async def test_send_async_blocked_raises(self) -> None:
        bus, _ = self._setup_bus()
        with pytest.raises(PermissionError):
            bus.send_async("blocked", "target", "hi")

    async def test_send_async_allowed_returns_task_id(self) -> None:
        bus, _ = self._setup_bus()
        task_id = bus.send_async("allowed", "target", "hi")
        assert task_id is not None

    async def test_bus_without_auth_allows_everything(self) -> None:
        """When no auth_registry, bus allows all sends (backward compat)."""
        bus = InterAgentBus()  # no auth_registry
        bus.register("target", _make_stack("ok"))
        result = await bus.send("anyone", "target", "hi")
        assert result.success is True


# ===========================================================================
# InternalAgentAPI auth integration
# ===========================================================================


@pytest.fixture
def auth_registry() -> AgentAuthRegistry:
    reg = AgentAuthRegistry()
    reg.reload(
        [
            _make_agent("sub1", secret="secret-sub1", can_contact=["sub2"]),
            _make_agent("sub2", secret="secret-sub2", accept_from=["sub1", "main"]),
        ],
        main_agent_secret="secret-main",
    )
    return reg


@pytest.fixture
def authed_bus(auth_registry: AgentAuthRegistry) -> InterAgentBus:
    bus = InterAgentBus(auth_registry=auth_registry)
    bus.register("sub1", _make_stack("from-sub1"))
    bus.register("sub2", _make_stack("from-sub2"))
    return bus


@pytest.fixture
def authed_api(authed_bus: InterAgentBus, auth_registry: AgentAuthRegistry) -> InternalAgentAPI:
    return InternalAgentAPI(authed_bus, port=0, auth_registry=auth_registry)


@pytest.fixture
async def authed_client(authed_api: InternalAgentAPI) -> AsyncClient:
    transport = ASGITransport(app=authed_api._app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestAPIAuthMissingHeader:
    """Request without Authorization header returns 401."""

    async def test_send_without_auth_header(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "sub1", "to": "sub2", "message": "hi"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["success"] is False
        assert "Authorization" in data["error"]

    async def test_send_async_without_auth_header(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send_async",
            json={"from": "sub1", "to": "sub2", "message": "hi"},
        )
        assert resp.status_code == 401


class TestAPIAuthInvalidToken:
    """Request with invalid token returns 401."""

    async def test_send_with_bad_token(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "sub1", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "Invalid" in data["error"]


class TestAPIAuthSpoofedSender:
    """Request with valid token but spoofed sender returns 403."""

    async def test_send_with_spoofed_sender(self, authed_client: AsyncClient) -> None:
        # sub1's token used but claiming to be main
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "main", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub1"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "mismatch" in data["error"]

    async def test_send_async_with_spoofed_sender(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send_async",
            json={"from": "main", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub1"},
        )
        assert resp.status_code == 403


class TestAPIAuthACLDenied:
    """Request with valid token, correct sender, but ACL denied returns 403."""

    async def test_send_acl_denied(self, authed_client: AsyncClient) -> None:
        # sub2 has no can_contact entries, so cannot reach sub1
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "sub2", "to": "sub1", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub2"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "blocked" in data["error"]

    async def test_send_async_acl_denied(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send_async",
            json={"from": "sub2", "to": "sub1", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub2"},
        )
        assert resp.status_code == 403


class TestAPIAuthSuccess:
    """Request with valid token, correct sender, ACL allowed succeeds."""

    async def test_send_authed_success(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "sub1", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["text"] == "from-sub2"

    async def test_send_async_authed_success(self, authed_client: AsyncClient) -> None:
        resp = await authed_client.post(
            "/interagent/send_async",
            json={"from": "sub1", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer secret-sub1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task_id" in data

    async def test_main_agent_authed_send(self, authed_client: AsyncClient) -> None:
        """Main agent with its token can reach any sub-agent."""
        resp = await authed_client.post(
            "/interagent/send",
            json={"from": "main", "to": "sub2", "message": "hi"},
            headers={"Authorization": "Bearer secret-main"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestAPINoAuthBackwardCompat:
    """API without auth_registry passes through (backward compat)."""

    @pytest.fixture
    def noauth_bus(self) -> InterAgentBus:
        bus = InterAgentBus()
        stack = _make_stack("ok")
        bus.register("target", stack)
        return bus

    @pytest.fixture
    def noauth_api(self, noauth_bus: InterAgentBus) -> InternalAgentAPI:
        return InternalAgentAPI(noauth_bus, port=0)

    @pytest.fixture
    async def noauth_client(self, noauth_api: InternalAgentAPI) -> AsyncClient:
        transport = ASGITransport(app=noauth_api._app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_send_without_auth_registry(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.post(
            "/interagent/send",
            json={"from": "anyone", "to": "target", "message": "hi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ===========================================================================
# SubAgentConfig security defaults
# ===========================================================================


class TestSubAgentConfigSecurityDefaults:
    """Test security-related defaults on SubAgentConfig."""

    def test_agent_secret_auto_generated(self) -> None:
        """Missing agent_secret gets a random hex value."""
        cfg = SubAgentConfig(name="test")
        assert cfg.agent_secret  # non-empty
        assert len(cfg.agent_secret) == 64  # secrets.token_hex(32) = 64 hex chars

    def test_agent_secret_unique_per_instance(self) -> None:
        cfg1 = SubAgentConfig(name="a")
        cfg2 = SubAgentConfig(name="b")
        assert cfg1.agent_secret != cfg2.agent_secret

    def test_explicit_agent_secret_preserved(self) -> None:
        cfg = SubAgentConfig(name="test", agent_secret="my-secret")
        assert cfg.agent_secret == "my-secret"

    def test_default_trust_level_is_restricted(self) -> None:
        cfg = SubAgentConfig(name="test")
        assert cfg.trust_level == "restricted"

    def test_default_accept_from_is_empty(self) -> None:
        """Empty default -- reload() decides open vs isolated based on linux_user."""
        cfg = SubAgentConfig(name="test")
        assert cfg.accept_from == []

    def test_default_can_contact_is_empty(self) -> None:
        cfg = SubAgentConfig(name="test")
        assert cfg.can_contact == []

    def test_security_fields_excluded_from_merge(self) -> None:
        """agent_secret, trust_level, can_contact, accept_from are excluded from merge."""
        from pathlib import Path

        from botwerk_bot.config import AgentConfig
        from botwerk_bot.multiagent.models import merge_sub_agent_config

        main = AgentConfig(
            provider="claude",
            model="opus",
            botwerk_home="/main",
        )
        sub = SubAgentConfig(
            name="sub",
            agent_secret="sub-secret",
            trust_level="privileged",
            can_contact=["other"],
            accept_from=["other"],
        )
        result = merge_sub_agent_config(main, sub, Path("/agents/sub"))

        # agent_secret is carried through explicitly
        assert result.agent_secret == "sub-secret"
        # trust_level, can_contact, accept_from are not AgentConfig fields,
        # so they should not cause errors or appear as extra keys


# ===========================================================================
# AgentACL dataclass
# ===========================================================================


class TestAgentACL:
    """Test AgentACL defaults."""

    def test_defaults(self) -> None:
        acl = AgentACL()
        assert acl.can_contact == []
        assert acl.accept_from == []
        assert acl.trust_level == "restricted"

    def test_custom_values(self) -> None:
        acl = AgentACL(
            can_contact=["a", "b"],
            accept_from=["c"],
            trust_level="privileged",
        )
        assert acl.can_contact == ["a", "b"]
        assert acl.accept_from == ["c"]
        assert acl.trust_level == "privileged"
