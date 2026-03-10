"""Tests for the exception hierarchy."""

from botwerk_bot.errors import (
    BotwerkError,
    CLIError,
    PathValidationError,
    SecurityError,
    WorkspaceError,
)


def test_base_error_is_exception() -> None:
    assert issubclass(BotwerkError, Exception)


def test_cli_error_inherits_base() -> None:
    err = CLIError("cli broke")
    assert isinstance(err, BotwerkError)
    assert str(err) == "cli broke"


def test_workspace_error_inherits_base() -> None:
    assert isinstance(WorkspaceError("no workspace"), BotwerkError)


def test_security_error_inherits_base() -> None:
    assert isinstance(SecurityError("blocked"), BotwerkError)


def test_path_validation_error_inherits_security() -> None:
    err = PathValidationError("outside root")
    assert isinstance(err, SecurityError)
    assert isinstance(err, BotwerkError)


def test_catch_all_with_base() -> None:
    """All subclasses catchable via BotwerkError."""
    for cls in (CLIError, WorkspaceError, SecurityError, PathValidationError):
        try:
            raise cls("test")
        except BotwerkError:
            pass
