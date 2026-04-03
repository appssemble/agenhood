import asyncio

import pytest
import sqlalchemy.pool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.tables import metadata, webhook_events  # noqa: F401
from connectors.webhook_dedupe import claim_delivery

pytestmark = pytest.mark.unit


@pytest.fixture
def factory():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    asyncio.run(_init(eng))
    return async_sessionmaker(eng, expire_on_commit=False)


async def _init(eng):
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)


def test_first_claim_true_second_false(factory):
    async def go():
        async with factory() as s:
            first = await claim_delivery(s, "github", "d-1", "digest")
            await s.commit()
        async with factory() as s:
            second = await claim_delivery(s, "github", "d-1", "digest")
            await s.commit()
        return first, second

    first, second = asyncio.run(go())
    assert first is True
    assert second is False
