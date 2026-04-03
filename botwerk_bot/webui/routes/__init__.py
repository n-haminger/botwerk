"""WebUI route modules.

Each module exports a ``create_*_router()`` factory that returns an APIRouter.
"""

from botwerk_bot.webui.routes.agent_routes import create_agent_router
from botwerk_bot.webui.routes.auth_routes import create_auth_router
from botwerk_bot.webui.routes.config_routes import create_config_router
from botwerk_bot.webui.routes.cron_routes import create_cron_router
from botwerk_bot.webui.routes.explorer_routes import create_explorer_router
from botwerk_bot.webui.routes.file_routes import create_file_router
from botwerk_bot.webui.routes.message_routes import create_message_router
from botwerk_bot.webui.routes.status_routes import create_status_router
from botwerk_bot.webui.routes.user_routes import create_user_router

__all__ = [
    "create_agent_router",
    "create_auth_router",
    "create_config_router",
    "create_cron_router",
    "create_explorer_router",
    "create_file_router",
    "create_message_router",
    "create_status_router",
    "create_user_router",
]
