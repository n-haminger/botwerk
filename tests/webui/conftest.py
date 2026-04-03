"""Shared fixtures for WebUI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from botwerk_bot.webui.models import Base

TEST_SECRET = "test-secret-key-for-jwt-signing-long-enough"
TEST_DB_PREFIX = "sqlite+aiosqlite:///"


@pytest_asyncio.fixture
async def db_engine(tmp_path: Path):
    """Create a temporary SQLite database engine with all tables."""
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"{TEST_DB_PREFIX}{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an async session for direct DB manipulation in tests."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def webui_app(db_engine, tmp_path):
    """Create a WebUI FastAPI app wired to the test database."""
    from botwerk_bot.config import WebUIConfig
    from botwerk_bot.webui.app import create_webui_app
    from botwerk_bot.webui.database import get_db

    upload_dir = tmp_path / "webui_uploads"
    config = WebUIConfig(enabled=True, secret_key=TEST_SECRET)
    app = create_webui_app(config, upload_dir=upload_dir)

    # Override the DB dependency to use our test engine.
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_get_db():
        async with factory() as session:
            yield session

    # The API sub-app is mounted at /api — we need to override on it too.
    for route in app.routes:
        if hasattr(route, "app") and hasattr(route.app, "dependency_overrides"):
            route.app.dependency_overrides[get_db] = _override_get_db

    # Set session_factory on app.state for WebSocket handler.
    app.state.session_factory = factory

    return app


@pytest_asyncio.fixture
async def client(webui_app):
    """AsyncClient for testing the WebUI app."""
    transport = ASGITransport(app=webui_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
