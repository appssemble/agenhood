from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from control_plane.config import Settings
from control_plane.models_db import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _url() -> str:
    return Settings.from_env().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), future=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
