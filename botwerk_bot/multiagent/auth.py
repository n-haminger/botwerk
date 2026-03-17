"""Authentication and authorization registry for inter-agent communication.

Holds per-agent secrets and ACLs. Both :class:`InternalAgentAPI` and
:class:`InterAgentBus` hold a reference to the same registry instance so
that every message — whether it arrives via HTTP or the in-memory bus —
goes through the same permission checks.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field

from botwerk_bot.multiagent.models import SubAgentConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentACL:
    """Per-agent access-control entry."""

    can_contact: list[str] = field(default_factory=list)
    accept_from: list[str] = field(default_factory=list)
    trust_level: str = "restricted"


class AgentAuthRegistry:
    """Shared mutable registry of agent tokens and ACLs.

    Rebuilt via :meth:`reload` whenever ``agents.json`` changes.
    """

    def __init__(self) -> None:
        self._token_to_agent: dict[str, str] = {}
        self._acls: dict[str, AgentACL] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reload(
        self,
        agents: list[SubAgentConfig],
        main_agent_name: str = "main",
        main_agent_secret: str = "",
    ) -> None:
        """Rebuild token map and ACLs from the current agent configs.

        *agents* contains only sub-agent definitions (not the main agent).
        The main agent is implicitly added with ``trust_level="privileged"``
        and ``can_contact=["*"]``.  If *main_agent_secret* is provided it is
        registered in the token map so CLI subprocesses of the main agent can
        authenticate.
        """
        token_map: dict[str, str] = {}
        acls: dict[str, AgentACL] = {}

        # Main agent — always privileged, can contact anyone.
        acls[main_agent_name] = AgentACL(
            can_contact=["*"],
            accept_from=["*"],
            trust_level="privileged",
        )
        if main_agent_secret:
            token_map[main_agent_secret] = main_agent_name

        for agent in agents:
            name = agent.name

            # Register token if present.
            if agent.agent_secret:
                token_map[agent.agent_secret] = name

            # Build ACL — linux_user agents are fully isolated by default.
            is_isolated = bool(agent.linux_user)

            if is_isolated:
                # Isolated agents: can't contact anyone, only accept from main.
                # Explicit config is ignored — isolation is enforced at this level.
                can_contact: list[str] = []
                accept_from = [main_agent_name]
            else:
                # Normal agents: open communication by default.
                # Empty lists (Pydantic default) → wildcard. Explicit config is respected.
                can_contact = list(agent.can_contact) if agent.can_contact else ["*"]
                accept_from = list(agent.accept_from) if agent.accept_from else ["*"]
                # Main can always contact sub-agents (implicit rule).
                if main_agent_name not in accept_from and "*" not in accept_from:
                    accept_from.append(main_agent_name)

            trust = agent.trust_level or "restricted"
            acls[name] = AgentACL(
                can_contact=can_contact,
                accept_from=accept_from,
                trust_level=trust,
            )

        # Atomic swap — both dicts are replaced in a single statement to
        # prevent an in-flight request from seeing a new token map with old ACLs.
        self._token_to_agent, self._acls = token_map, acls
        logger.debug(
            "Auth registry reloaded: %d agent(s), %d token(s)",
            len(acls),
            len(token_map),
        )

    # ------------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------------

    def verify_token(self, token: str) -> str | None:
        """Return agent name for a valid token, ``None`` otherwise.

        Uses constant-time comparison to prevent timing side-channels.
        """
        for registered_token, agent_name in self._token_to_agent.items():
            if hmac.compare_digest(registered_token, token):
                return agent_name
        return None

    # ------------------------------------------------------------------
    # ACL checks
    # ------------------------------------------------------------------

    def can_send(self, sender: str, recipient: str) -> bool:
        """Check whether *sender* is allowed to contact *recipient*.

        Rules:
        1. Privileged agents with ``can_contact=["*"]`` may contact anyone.
        2. Otherwise *recipient* must appear in the sender's ``can_contact``.
        3. The recipient's ``accept_from`` must include the sender (or ``"*"``).
        """
        sender_acl = self._acls.get(sender)
        if sender_acl is None:
            return False

        # Sender allowed to contact recipient?
        if "*" not in sender_acl.can_contact and recipient not in sender_acl.can_contact:
            return False

        # Recipient accepts from sender?
        recipient_acl = self._acls.get(recipient)
        if recipient_acl is None:
            return False
        return "*" in recipient_acl.accept_from or sender in recipient_acl.accept_from

    def explain_block(self, sender: str, recipient: str) -> str:
        """Return a human-readable explanation of why *sender* cannot contact *recipient*."""
        sender_acl = self._acls.get(sender)
        if sender_acl is None:
            return (
                f"Inter-agent communication blocked: agent '{sender}' is not registered. "
                "Only registered agents can send messages."
            )
        if not sender_acl.can_contact or (
            "*" not in sender_acl.can_contact and recipient not in sender_acl.can_contact
        ):
            return (
                f"Inter-agent communication blocked: agent '{sender}' is not allowed "
                f"to contact '{recipient}'. Your can_contact list does not include this "
                "agent. This is enforced by the inter-agent security policy in agents.json. "
                "If you are an isolated agent (linux_user), you cannot initiate contact "
                "with any other agent — only the main agent can send messages to you."
            )
        recipient_acl = self._acls.get(recipient)
        if recipient_acl is None:
            return (
                f"Inter-agent communication blocked: agent '{recipient}' is not registered."
            )
        return (
            f"Inter-agent communication blocked: agent '{recipient}' does not accept "
            f"messages from '{sender}'. The recipient's accept_from list does not "
            "include your agent name."
        )

    def get_trust_level(self, agent_name: str) -> str:
        """Return the trust level for *agent_name* (default ``"restricted"``)."""
        acl = self._acls.get(agent_name)
        return acl.trust_level if acl else "restricted"
