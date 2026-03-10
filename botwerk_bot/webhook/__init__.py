"""Webhook system: HTTP ingress for external event triggers."""

from botwerk_bot.webhook.manager import WebhookManager
from botwerk_bot.webhook.models import WebhookEntry, WebhookResult

__all__ = ["WebhookEntry", "WebhookManager", "WebhookResult"]
