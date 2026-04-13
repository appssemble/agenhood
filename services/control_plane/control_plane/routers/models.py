from __future__ import annotations

from collections.abc import AsyncIterator

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.model_catalog import annotate, methods_from_credential_rows

router = APIRouter()


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


@router.get("/models")
async def list_models(
    request: Request,
    driver: str | None = None,
    p: Principal = Depends(resolve_principal),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    catalog = request.app.state.model_catalog
    rows: list[dict] = []  # type: ignore[type-arg]
    if p.tenant_id is not None:
        rows = [
            dict(r) for r in (
                await conn.execute(
                    sa.select(
                        t.credentials.c.provider,
                        t.credentials.c.auth_method,
                        t.credentials.c.status,
                    ).where(t.credentials.c.tenant_id == p.tenant_id)
                )
            ).mappings().all()
        ]
    methods = methods_from_credential_rows(rows)
    return {"models": annotate(catalog, driver, methods)}
