"""Multi-agent architecture: supervisor, bus, and inter-agent communication."""

from botwerk_bot.multiagent.bus import InterAgentBus
from botwerk_bot.multiagent.health import AgentHealth
from botwerk_bot.multiagent.models import SubAgentConfig
from botwerk_bot.multiagent.supervisor import AgentSupervisor

__all__ = ["AgentHealth", "AgentSupervisor", "InterAgentBus", "SubAgentConfig"]
