"""Tests for the message hook system."""

from __future__ import annotations

from botwerk_bot.orchestrator.hooks import (
    HookContext,
    MessageHook,
    MessageHookRegistry,
    every_n_messages,
)

# ---------------------------------------------------------------------------
# Unit tests: HookContext, conditions, registry
# ---------------------------------------------------------------------------


def _ctx(*, message_count: int = 0, is_new: bool = False) -> HookContext:
    return HookContext(
        chat_id=1,
        message_count=message_count,
        is_new_session=is_new,
        provider="claude",
        model="opus",
    )


class TestEveryNMessages:
    def test_fires_on_nth_message(self) -> None:
        check = every_n_messages(6)
        # message_count is pre-increment: count=5 -> 6th message
        assert check(_ctx(message_count=5)) is True

    def test_fires_on_multiples(self) -> None:
        check = every_n_messages(6)
        assert check(_ctx(message_count=11)) is True  # 12th
        assert check(_ctx(message_count=17)) is True  # 18th

    def test_does_not_fire_on_first(self) -> None:
        check = every_n_messages(6)
        assert check(_ctx(message_count=0)) is False

    def test_does_not_fire_between_intervals(self) -> None:
        check = every_n_messages(6)
        for count in (1, 2, 3, 4, 6, 7, 8, 9, 10):
            assert check(_ctx(message_count=count)) is False

    def test_interval_of_1(self) -> None:
        check = every_n_messages(1)
        assert check(_ctx(message_count=0)) is True
        assert check(_ctx(message_count=1)) is True
        assert check(_ctx(message_count=99)) is True

    def test_interval_of_3(self) -> None:
        check = every_n_messages(3)
        assert check(_ctx(message_count=2)) is True  # 3rd
        assert check(_ctx(message_count=5)) is True  # 6th
        assert check(_ctx(message_count=1)) is False
        assert check(_ctx(message_count=3)) is False


class TestMessageHookRegistry:
    def test_no_hooks_returns_original(self) -> None:
        reg = MessageHookRegistry()
        assert reg.apply("hello", _ctx()) == "hello"

    def test_matching_hook_appends_suffix(self) -> None:
        reg = MessageHookRegistry()
        hook = MessageHook(name="test", condition=lambda _: True, suffix="## Reminder")
        reg.register(hook)
        result = reg.apply("hello", _ctx())
        assert result == "hello\n\n## Reminder"

    def test_non_matching_hook_ignored(self) -> None:
        reg = MessageHookRegistry()
        hook = MessageHook(name="test", condition=lambda _: False, suffix="## Reminder")
        reg.register(hook)
        assert reg.apply("hello", _ctx()) == "hello"

    def test_multiple_hooks_concatenated(self) -> None:
        reg = MessageHookRegistry()
        reg.register(MessageHook(name="a", condition=lambda _: True, suffix="A"))
        reg.register(MessageHook(name="b", condition=lambda _: True, suffix="B"))
        result = reg.apply("hello", _ctx())
        assert result == "hello\n\nA\n\nB"

    def test_mixed_matching(self) -> None:
        reg = MessageHookRegistry()
        reg.register(MessageHook(name="yes", condition=lambda _: True, suffix="YES"))
        reg.register(MessageHook(name="no", condition=lambda _: False, suffix="NO"))
        result = reg.apply("hello", _ctx())
        assert result == "hello\n\nYES"
        assert "NO" not in result


# NOTE: TestMainmemoryReminder and integration tests removed.
# The MAINMEMORY_REMINDER hook has been replaced by the autonomous
# MemoryObserver (botwerk_bot.memory).  See tests/memory/ for coverage.
