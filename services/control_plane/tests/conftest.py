from __future__ import annotations

import shutil
import subprocess

import pytest
import pytest_asyncio


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except Exception:
        return False


DOCKER_AVAILABLE = docker_available()

requires_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE, reason="docker daemon not available"
)


if DOCKER_AVAILABLE:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    @pytest_asyncio.fixture(scope="session")
    async def pg_container():
        """Start a throwaway Postgres container for the test session."""
        with PostgresContainer("postgres:16") as pg:
            yield pg

    @pytest_asyncio.fixture(scope="session")
    async def migrated_db_url(pg_container):
        """Return the async DB URL after applying the schema to a throwaway Postgres.

        We use SQLAlchemy metadata.create_all() via the async engine so no
        psycopg2 dependency is needed (we only have asyncpg). The Alembic
        migration is exercised separately in the service directory.
        """
        from sqlalchemy.ext.asyncio import create_async_engine

        from control_plane.models_db import metadata

        async_url = pg_container.get_connection_url(driver="asyncpg")

        engine = create_async_engine(async_url, future=True)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await engine.dispose()

        return async_url

    @pytest_asyncio.fixture()
    async def db_session(migrated_db_url):
        """Yield a fresh AsyncSession against the migrated test database."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        engine = create_async_engine(migrated_db_url, pool_pre_ping=True, future=True)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
            await session.rollback()  # each test gets a clean slate
        await engine.dispose()

else:
    @pytest_asyncio.fixture()
    async def db_session():
        pytest.skip("docker daemon not available")
        yield  # type: ignore[misc]
