"""CLI layer: provider abstraction, process tracking, streaming."""

from botwerk_bot.cli.auth import AuthResult as AuthResult
from botwerk_bot.cli.auth import AuthStatus as AuthStatus
from botwerk_bot.cli.auth import check_all_auth as check_all_auth
from botwerk_bot.cli.base import BaseCLI as BaseCLI
from botwerk_bot.cli.base import CLIConfig as CLIConfig
from botwerk_bot.cli.coalescer import CoalesceConfig as CoalesceConfig
from botwerk_bot.cli.coalescer import StreamCoalescer as StreamCoalescer
from botwerk_bot.cli.factory import create_cli as create_cli
from botwerk_bot.cli.process_registry import ProcessRegistry as ProcessRegistry
from botwerk_bot.cli.service import CLIService as CLIService
from botwerk_bot.cli.service import CLIServiceConfig as CLIServiceConfig
from botwerk_bot.cli.types import AgentRequest as AgentRequest
from botwerk_bot.cli.types import AgentResponse as AgentResponse
from botwerk_bot.cli.types import CLIResponse as CLIResponse

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "AuthResult",
    "AuthStatus",
    "BaseCLI",
    "CLIConfig",
    "CLIResponse",
    "CLIService",
    "CLIServiceConfig",
    "CoalesceConfig",
    "ProcessRegistry",
    "StreamCoalescer",
    "check_all_auth",
    "create_cli",
]
