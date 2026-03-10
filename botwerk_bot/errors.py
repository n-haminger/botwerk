"""Project-level exception hierarchy."""


class BotwerkError(Exception):
    """Base for all botwerk exceptions."""


class CLIError(BotwerkError):
    """CLI execution failed."""


class WorkspaceError(BotwerkError):
    """Workspace initialization or access failed."""


class SessionError(BotwerkError):
    """Session persistence or lifecycle failed."""


class CronError(BotwerkError):
    """Cron job scheduling or execution failed."""


class StreamError(BotwerkError):
    """Streaming output failed."""


class SecurityError(BotwerkError):
    """Security violation detected."""


class PathValidationError(SecurityError):
    """File path failed validation."""


class WebhookError(BotwerkError):
    """Webhook server or dispatch failed."""
