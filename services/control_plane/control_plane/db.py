from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from control_plane.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    # Slow container provisions hold checked-out connections (create route),
    # so the pool gets explicit, env-tunable headroom (DB_POOL_SIZE/DB_MAX_OVERFLOW).
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
