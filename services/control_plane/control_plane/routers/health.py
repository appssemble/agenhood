"""Public, unauthenticated health endpoint (spec §12).

GET /healthz -> 200 {"status":"ok"} if `SELECT 1` succeeds, else 503.
The DB check is a FastAPI dependency so it can be injected/overridden in tests.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["Health"])

DbCheck = Callable[[], Awaitable[None]]


def db_check(request: Request) -> DbCheck:
    """Indirection so tests can override the check via dependency_overrides.

    Returns a no-arg awaitable that raises if Postgres is unreachable. ``request``
    is injected by FastAPI (db_check is itself a dependency), so the returned
    closure needs no arguments — matching how ``healthz`` calls ``check()``.
    """

    async def _check() -> None:
        factory = request.app.state.session_factory
        async with factory() as session:
            await session.execute(text("SELECT 1"))

    return _check


@router.get(
    "/healthz",
    response_model=None,
    response_description=(
        "`{\"status\": \"ok\"}` with HTTP 200 when Postgres is reachable, or "
        "`{\"status\": \"unavailable\"}` with HTTP 503 when the `SELECT 1` "
        "readiness probe fails."
    ),
)
async def healthz(
    request: Request, check: DbCheck = Depends(db_check)
) -> JSONResponse:
    """Report control-plane liveness/readiness (spec §12).

    Public and unauthenticated; mounted at the application root with no `/v1`
    prefix. Runs a `SELECT 1` against Postgres to confirm the database is
    reachable.

    Returns HTTP 200 with `{"status": "ok"}` when the check succeeds, or HTTP
    503 with `{"status": "unavailable"}` when Postgres is unreachable (any
    exception from the check is treated as an unhealthy signal). Never raises.
    """
    try:
        await check()
    except Exception:  # noqa: BLE001 — any DB failure is an unhealthy signal
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})
