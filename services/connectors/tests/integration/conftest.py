from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.tables import metadata

pytestmark = pytest.mark.integration

_KEY = os.urandom(32)
# Derived from the live metadata (reverse topological order so FK children
# truncate before parents) so a future table is covered automatically and
# per-test isolation can't silently rot.
_TABLES = [t.name for t in reversed(metadata.sorted_tables)]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        return True
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()


@pytest.fixture(scope="session")
def pg_url():
    if not DOCKER_AVAILABLE:
        pytest.skip("docker daemon not available")
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer("postgres:16") as pg:
        url = pg.get_connection_url(driver="asyncpg")
        if not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        async def _create() -> None:
            eng = create_async_engine(url)
            async with eng.begin() as conn:
                await conn.run_sync(metadata.create_all)
            await eng.dispose()

        asyncio.run(_create())
        yield url


@pytest_asyncio.fixture
async def session_factory(pg_url):
    # Fresh engine per test so the engine binds to this test's event loop
    # (pytest-asyncio strict mode gives each test a new loop).
    eng = create_async_engine(pg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    # Clean slate: previous tests commit through their own sessions.
    async with eng.begin() as conn:
        await conn.execute(sa.text(
            "TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield factory
    await eng.dispose()


@pytest.fixture
def master_key() -> bytes:
    return _KEY


@pytest.fixture
def pg_app(pg_url, master_key):
    """A create_app() wired to Postgres + injectable provider/CP stubs.

    Returns a builder: call build(providers=..., cp_client=...) -> TestClient.

    Each build() call creates a fresh engine so that TestClient's anyio event
    loop owns all asyncpg connections — avoids the cross-loop RuntimeError that
    occurs when the test's async-fixture engine (bound to pytest-asyncio's loop)
    is handed to TestClient's separate anyio loop.
    """
    import base64

    from fastapi.testclient import TestClient

    from connectors.app import create_app

    os.environ["CONNECTORS_MASTER_KEY"] = base64.b64encode(master_key).decode()

    def build(*, providers, cp_client):
        app = create_app(start_background=False)
        # Fresh engine per build() — first connection is established inside
        # TestClient's loop, so asyncpg binds to the correct event loop.
        eng = create_async_engine(pg_url, pool_pre_ping=True, future=True)
        app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
        app.state.master_key = master_key
        app.state.providers = providers
        app.state.cp_client = cp_client
        return TestClient(app)

    return build
