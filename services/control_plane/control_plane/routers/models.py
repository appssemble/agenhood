from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.model_catalog import annotate, methods_from_credential_rows

router = APIRouter(tags=["Models"])


class ModelInfo(BaseModel):
    id: str = Field(description="Catalog model identifier (e.g. `provider/model`).")
    provider: str = Field(
        description="Provider that serves the model (e.g. `anthropic`, `openai`)."
    )
    label: str = Field(description="Human-readable display name for the model.")
    category: str = Field(description="Catalog category grouping for the model.")
    drivers: list[str] = Field(description="Agent drivers that can run this model.")
    available: bool = Field(
        description="True when the caller's tenant has a credential that can run the model."
    )
    requires: list[str] = Field(
        description=(
            "Auth methods that would make the model available; empty when already "
            "available."
        )
    )


class ModelsResponse(BaseModel):
    models: list[ModelInfo] = Field(
        description="Catalog models annotated with per-tenant availability."
    )


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


@router.get(
    "/models",
    response_model=ModelsResponse,
    response_description="The model catalog annotated with availability for the caller's tenant.",
)
async def list_models(
    request: Request,
    driver: Annotated[
        str | None,
        Query(
            description=(
                "Optional agent driver to filter the catalog to models that driver can run."
            )
        ),
    ] = None,
    p: Principal = Depends(resolve_principal),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List available models, annotated with per-tenant availability.

    Returns the model catalog, optionally filtered by `driver`. When the caller
    is tenant-scoped, each model is annotated with whether the tenant's stored
    credentials can run it (`available`) and, if not, which auth methods would
    unlock it (`requires`). Staff credentials (tenant_id=None) see the catalog
    with no tenant credentials applied, so models requiring credentials are
    reported as unavailable.

    Any authenticated principal may call this endpoint (no side effects).
    """
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
