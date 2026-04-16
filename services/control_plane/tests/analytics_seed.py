"""Row-insert helpers for analytics tests (direct table inserts via a session)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from control_plane.models_db import containers, tasks, tenants

_CFG: dict[str, Any] = {
    "driver": "vanilla", "model": "m", "system_prompt": "",
    "system_prompt_mode": "augment", "tools": [],
    "context": {"variables": {}, "text": None, "files": []},
}


async def insert_tenant(session: Any, tenant_id: str, name: str = "Acme") -> None:
    # Provide explicit values for all NOT NULL columns instead of relying on
    # server_defaults, which can be stripped from the shared Table object when
    # create_app is imported by other unit tests before the session-scoped
    # metadata.create_all() runs.
    await session.execute(
        sa.insert(tenants).values(
            id=tenant_id,
            name=name,
            limits={},
            status="active",
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def insert_container(session: Any, *, cid: str, tenant_id: str, name: str,
                           status: str = "running") -> None:
    await session.execute(sa.insert(containers).values(
        id=cid, tenant_id=tenant_id, name=name,
        docker_name=f"dn-{cid}", volume_name=f"vol-{cid}", shim_token="tok",
        image_tag="t", config=_CFG, status=status,
    ))
    await session.commit()


async def insert_task(session: Any, *, tid: str, tenant_id: str, container_id: str,
                      created_at: datetime, tokens_in: int = 0, tokens_out: int = 0,
                      iterations: int = 0, status: str = "completed",
                      driver: str = "vanilla", model: str | None = "m") -> None:
    await session.execute(sa.insert(tasks).values(
        id=tid, tenant_id=tenant_id, container_id=container_id,
        driver=driver, model=model, body={"prompt": "p"}, config_snapshot=_CFG,
        status=status, tokens_in=tokens_in, tokens_out=tokens_out,
        iterations_used=iterations, created_at=created_at,
    ))
    await session.commit()
