"""Tests for the transport registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from botwerk_bot.transport_registry import create_bot


class TestTransportRegistry:
    def test_unknown_transport_raises(self) -> None:
        config = MagicMock()
        config.transport = "discord"
        with pytest.raises(ValueError, match="Unknown transport.*discord"):
            create_bot(config)

    def test_telegram_transport(self) -> None:
        config = MagicMock()
        config.transport = "telegram"
        fake_bot = MagicMock()
        with patch("botwerk_bot.bot.app.TelegramBot", return_value=fake_bot):
            bot = create_bot(config, agent_name="test")
        assert bot is fake_bot

    def test_matrix_transport(self) -> None:
        config = MagicMock()
        config.transport = "matrix"
        config.matrix = MagicMock()
        config.matrix.homeserver = "https://matrix.example.com"
        fake_bot = MagicMock()
        with patch("botwerk_bot.matrix.bot.MatrixBot", return_value=fake_bot):
            bot = create_bot(config, agent_name="test")
        assert bot is fake_bot

    def test_matrix_transport_no_homeserver_raises(self) -> None:
        config = MagicMock()
        config.transport = "matrix"
        config.matrix = MagicMock()
        config.matrix.homeserver = ""
        with pytest.raises(ValueError, match="no homeserver configured"):
            create_bot(config, agent_name="test")

    def test_matrix_transport_no_matrix_config_raises(self) -> None:
        config = MagicMock()
        config.transport = "matrix"
        config.matrix = None
        with pytest.raises(ValueError, match="no homeserver configured"):
            create_bot(config, agent_name="test")
