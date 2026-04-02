from __future__ import annotations

import asyncio
import os
import pathlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

# Absolute path to services/connectors/ so paths work regardless of pytest CWD.
_SVC_ROOT = pathlib.Path(__file__).parents[1]


def test_tables_exist_after_migration() -> None:
    """Start a throwaway Postgres, run the real Alembic migration, assert tables.

    This is a *sync* test on purpose: connectors/migrations/env.py calls
    asyncio.run() at module scope, which would raise "cannot be called from a
    running event loop" inside an async test.  A plain sync function has no
    running loop, so asyncio.run() inside alembic's env.py works fine.  The
    async table-existence check is wrapped in a small asyncio.run() call at the
    end for the same reason.
    """
    from alembic import command
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    prev_url = os.environ.get("CONNECTORS_DATABASE_URL")
    try:
        with PostgresContainer("postgres:16") as pg:
            url: str = pg.get_connection_url(driver="asyncpg")
            # Ensure the scheme is postgresql+asyncpg:// (testcontainers >= 4
            # already includes the driver prefix, but guard just in case).
            if not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

            # Point the connectors Settings (read inside env.py) at the container.
            os.environ["CONNECTORS_DATABASE_URL"] = url

            # Run the real Alembic upgrade so 0001_initial is genuinely exercised.
            cfg = Config(str(_SVC_ROOT / "alembic.ini"))
            cfg.set_main_option(
                "script_location",
                str(_SVC_ROOT / "connectors" / "migrations"),
            )
            command.upgrade(cfg, "head")

            # Verify every expected table was created.
            async def _check_tables() -> set[str]:
                eng = create_async_engine(url)
                async with eng.connect() as conn:
                    rows = await conn.execute(
                        sa.text(
                            "select tablename from pg_tables where schemaname='public'"
                        )
                    )
                    names = {r[0] for r in rows}
                await eng.dispose()
                return names

            names = asyncio.run(_check_tables())
    finally:
        # Restore (or remove) the env var so later tests are not affected.
        if prev_url is None:
            os.environ.pop("CONNECTORS_DATABASE_URL", None)
        else:
            os.environ["CONNECTORS_DATABASE_URL"] = prev_url

    assert {
        "connections",
        "container_bindings",
        "routing_rules",
        "deliveries",
        "webhook_events",
        "action_log",
    } <= names
