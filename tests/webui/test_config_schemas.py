"""Tests for WebUIConfig defaults and Pydantic schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from botwerk_bot.config import WebUIConfig
from botwerk_bot.webui.schemas import MessageCreate, UserCreate


class TestWebUIConfigDefaults:
    def test_defaults(self):
        config = WebUIConfig()
        assert config.enabled is False
        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.behind_proxy is False
        assert config.secret_key == ""
        assert config.frontend_dir == ""

    def test_enabled_override(self):
        config = WebUIConfig(enabled=True, secret_key="some-key")
        assert config.enabled is True
        assert config.secret_key == "some-key"

    def test_custom_host_port(self):
        config = WebUIConfig(host="0.0.0.0", port=9090)
        assert config.host == "0.0.0.0"
        assert config.port == 9090


class TestUserCreateSchema:
    def test_valid_user(self):
        u = UserCreate(username="admin", password="securepass1")
        assert u.username == "admin"
        assert u.password == "securepass1"
        assert u.display_name == ""

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            UserCreate(username="a", password="securepass1")

    def test_username_too_long(self):
        with pytest.raises(ValidationError):
            UserCreate(username="x" * 65, password="securepass1")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            UserCreate(username="admin", password="short")

    def test_password_too_long(self):
        with pytest.raises(ValidationError):
            UserCreate(username="admin", password="x" * 129)

    def test_display_name_optional(self):
        u = UserCreate(username="admin", password="securepass1")
        assert u.display_name == ""

    def test_display_name_provided(self):
        u = UserCreate(username="admin", password="securepass1", display_name="Admin")
        assert u.display_name == "Admin"


class TestMessageCreateSchema:
    def test_valid_roles(self):
        for role in ("user", "assistant", "system"):
            m = MessageCreate(agent_name="main", role=role, content="hi")
            assert m.role == role

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError):
            MessageCreate(agent_name="main", role="invalid", content="hi")

    def test_metadata_json_optional(self):
        m = MessageCreate(agent_name="main", role="user", content="hi")
        assert m.metadata_json is None

    def test_metadata_json_provided(self):
        m = MessageCreate(agent_name="main", role="user", content="hi", metadata_json='{"k":"v"}')
        assert m.metadata_json == '{"k":"v"}'
