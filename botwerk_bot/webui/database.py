"""SQLite database setup with async SQLAlchemy 2.0 + aiosqlite."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(db_path: str) -> AsyncEngine:
    """Create the async engine, enable WAL mode, and create all tables.

    Returns the engine for use in tests or shutdown.
    """
    global _engine, _session_factory  # noqa: PLW0603

    url = f"sqlite+aiosqlite:///{db_path}"
    _engine = create_async_engine(url, echo=False)

    # Enable WAL mode for better concurrent read performance.
    async with _engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")

    # Import models so metadata is populated before create_all.
    from botwerk_bot.webui.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("WebUI database initialized: %s", db_path)
    return _engine


async def close_db() -> None:
    """Dispose of the engine and release all connections."""
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("WebUI database closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    async with _session_factory() as session:
        yield session
