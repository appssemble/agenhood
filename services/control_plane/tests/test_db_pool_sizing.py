from __future__ import annotations

import pytest

from control_plane.config import Settings
from control_plane.db import make_engine

pytestmark = pytest.mark.unit


def _settings(**kw) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk",
        seed_llm_api_key="",
        agent_image_tag="dev",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
    )
    base.update(kw)
    return Settings(**base)


def test_engine_uses_configured_pool_sizing() -> None:
    eng = make_engine(_settings(db_pool_size=7, db_max_overflow=13))
    pool = eng.sync_engine.pool
    assert pool.size() == 7
    assert pool._max_overflow == 13  # QueuePool exposes no public overflow getter
