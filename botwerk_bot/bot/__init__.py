"""Telegram bot interface."""

from botwerk_bot.bot.abort import ABORT_WORDS, is_abort_message, is_abort_trigger
from botwerk_bot.bot.app import TelegramBot
from botwerk_bot.bot.dedup import DedupeCache, build_dedup_key
from botwerk_bot.bot.edit_streaming import EditStreamEditor
from botwerk_bot.bot.formatting import (
    TELEGRAM_MSG_LIMIT,
    markdown_to_telegram_html,
    split_html_message,
)
from botwerk_bot.bot.middleware import AuthMiddleware, SequentialMiddleware
from botwerk_bot.bot.sender import send_file, send_rich
from botwerk_bot.bot.streaming import StreamEditor, StreamEditorProtocol, create_stream_editor
from botwerk_bot.bot.typing import TypingContext
from botwerk_bot.files.tags import extract_file_paths

__all__ = [
    "ABORT_WORDS",
    "TELEGRAM_MSG_LIMIT",
    "AuthMiddleware",
    "DedupeCache",
    "EditStreamEditor",
    "SequentialMiddleware",
    "StreamEditor",
    "StreamEditorProtocol",
    "TelegramBot",
    "TypingContext",
    "build_dedup_key",
    "create_stream_editor",
    "extract_file_paths",
    "is_abort_message",
    "is_abort_trigger",
    "markdown_to_telegram_html",
    "send_file",
    "send_rich",
    "split_html_message",
]
