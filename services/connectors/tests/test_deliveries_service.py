from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.deliveries_service import build_delivery_row, find_open_delivery_for_thread
from connectors.tables import deliveries, metadata

pytestmark = pytest.mark.unit


def test_build_delivery_row():
    row = build_delivery_row(
        task_id="tsk_1", container_id="cnt_1", connection_id="con_1",
        origin_ref={"channel": "C1", "thread_ts": "100"},
        surface=["reasoning", "result"],
    )
    assert row["task_id"] == "tsk_1"
    assert row["state"] == "streaming"
    assert row["last_seq"] == 0
    assert row["id"].startswith("dlv_")


def test_find_open_delivery_for_thread():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _run() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)

        session_factory = async_sessionmaker(eng, expire_on_commit=False)

        # Seed one delivery row
        row = build_delivery_row(
            task_id="tsk_seed",
            container_id="cnt_1",
            connection_id="con_1",
            origin_ref={"channel": "C1", "thread_ts": "100"},
            surface=["reasoning", "result"],
        )
        async with eng.begin() as conn:
            await conn.execute(sa.insert(deliveries).values(**row))

        # Match: same channel + thread_ts
        async with session_factory() as session:
            found = await find_open_delivery_for_thread(
                session,
                connection_id="con_1",
                thread_key_origin={"channel": "C1", "thread_ts": "100"},
            )
        assert found is not None
        assert found["task_id"] == "tsk_seed"

        # No match: different thread_ts
        async with session_factory() as session:
            not_found = await find_open_delivery_for_thread(
                session,
                connection_id="con_1",
                thread_key_origin={"channel": "C1", "thread_ts": "999"},
            )
        assert not_found is None

    asyncio.run(_run())
