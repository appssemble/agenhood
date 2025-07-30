from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import docker
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from control_plane.config import Settings
from control_plane.db import make_engine, make_session_factory
from control_plane.dormant import archive_sweep, reclaim_sweep
from control_plane.errors import (
    APIError,
    api_error_handler,
    request_validation_error_handler,
)
from control_plane.idle import idle_pause_sweep
from control_plane.logging_setup import setup_logging
from control_plane.reconciler import periodic_sweep, reconcile_all
from control_plane.routers import admin as admin_router
from control_plane.routers import api_keys as api_keys_router
from control_plane.routers import auth as auth_router
from control_plane.routers import credentials as credentials_router
from control_plane.routers import health as health_router
from control_plane.routers import tenants as tenants_router
from control_plane.routers import users as users_router
from control_plane.routers.analytics import router as analytics_router
from control_plane.routers.console import router as console_router
from control_plane.routers.containers import router as containers_router
from control_plane.routers.files import router as files_router
from control_plane.routers.git import router as git_router
from control_plane.routers.images import router as images_router
from control_plane.routers.mcp_servers import router as mcp_servers_router
from control_plane.routers.models import router as models_router
from control_plane.routers.prompts import router as prompts_router
from control_plane.routers.scheduled_tasks import router as scheduled_tasks_router
from control_plane.routers.skills import router as skills_router
from control_plane.routers.tasks import router as tasks_router
from control_plane.routers.templates import router as templates_router
from control_plane.routers.workflows import router as workflows_router
from control_plane.scheduler import _SCHEDULER_INTERVAL, scheduler_sweep
from control_plane.volume_check import volume_size_sweep

log = logging.getLogger("control_plane.app")

# Periodic reconcile interval (seconds).  Fast enough to catch crashes promptly
# without hammering docker inspect on every container every second.
_RECONCILE_INTERVAL = 180

# Idle-pause sweep cadence (spec §4.8): every minute.
_IDLE_PAUSE_SWEEP_INTERVAL = 60

# Dormant sweep cadences (spec §4.13).
_ARCHIVE_SWEEP_INTERVAL = 3600    # every hour — picks up paused→archive candidates
_RECLAIM_SWEEP_INTERVAL = 86400   # daily — picks up archived→reclaim candidates

# Volume size check interval (spec §8.4): daily.
_VOLUME_CHECK_INTERVAL_SECONDS = 86400


class _NoopShim:
    """Minimal shim stub used by the reconciler when no real ShimClient is available.

    The startup reconciler calls ``shim.post(cid, "/shutdown", best_effort=True)``
    as a best-effort pre-stop signal.  At startup the containers may not be
    reachable (the control plane itself just restarted), so silently swallowing
    the call is correct.
    """

    async def post(self, cid: str, path: str, *, best_effort: bool = False) -> None:  # noqa: ARG002
        pass

    async def cancel_all(self, cid: str) -> None:  # noqa: ARG002
        pass


class _ContainerShimDispatcher:
    """App-level shim dispatcher: resolves per-container shim URLs from the DB and
    issues shutdown/cancel_all calls to real running containers.

    Used for lifecycle operations (pause/recover) that need to signal individual
    containers.  Falls back silently when a container is unreachable.
    """

    def __init__(self, session_factory: Any, shim_port: int) -> None:
        self._factory = session_factory
        self._shim_port = shim_port

    async def _shim_for_cid(self, cid: str) -> Any:
        """Return an async context manager wrapping a ShimClient for the container."""
        from sqlalchemy import text as _text

        from control_plane.shim_client import ShimClient

        async with self._factory() as db:
            res = await db.execute(
                _text(
                    "SELECT docker_name, shim_token, resources FROM containers WHERE id = :cid"
                ),
                {"cid": cid},
            )
            row = res.first()
        if row is None:
            return None
        docker_name, shim_token, resources = row
        resources = resources or {}
        host_shim_url = resources.get("_host_shim_url") if isinstance(resources, dict) else None
        base_url = host_shim_url or f"http://{docker_name}:{self._shim_port}"
        return ShimClient(base_url=base_url, token=shim_token)

    async def post(self, cid: str, path: str, *, best_effort: bool = False) -> None:
        """POST *path* to the container's shim; silently ignores errors when best_effort."""
        try:
            shim = await self._shim_for_cid(cid)
            if shim is None:
                return
            async with shim:
                await shim._client.post(path)
        except Exception:  # noqa: BLE001
            if not best_effort:
                raise

    async def cancel_all(self, cid: str) -> None:
        """Cancel every active task on *cid* via the shim's cancel endpoint."""
        from sqlalchemy import text as _text

        # Load all running/pending tasks for this container.
        async with self._factory() as db:
            res = await db.execute(
                _text(
                    "SELECT id FROM tasks "
                    "WHERE container_id = :cid AND status IN ('pending','running')"
                ),
                {"cid": cid},
            )
            task_ids = [str(r[0]) for r in res.fetchall()]

        if not task_ids:
            return

        shim = await self._shim_for_cid(cid)
        if shim is None:
            return
        async with shim:
            for tid in task_ids:
                try:
                    await shim.cancel_task(tid)
                except Exception:  # noqa: BLE001
                    pass  # Best-effort: continue cancelling remaining tasks.


async def _bg_loop(
    session_factory: Any,
    docker_client: Any,
    shim: Any,
    fn: Any,
    *,
    interval: int,
    fn_kwargs: dict[str, Any] | None = None,
) -> None:
    """Run fn(db, docker_client, shim, **fn_kwargs) every *interval* s, catching errors."""
    bg_log = logging.getLogger("bg")
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                await fn(db, docker_client, shim, **(fn_kwargs or {}))
        except Exception:  # noqa: BLE001
            bg_log.exception("background loop %s failed", fn.__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: startup reconcile (before listener opens) + periodic sweeps."""
    session_factory = app.state.session_factory
    try:
        docker_client: Any = docker.from_env()
    except Exception:  # noqa: BLE001
        log.warning("Docker socket unavailable at startup; reconciler will be a no-op")
        docker_client = None

    # Use the real dispatcher if Docker is available; fall back to noop for
    # the startup reconciler (containers not yet reachable at boot).
    startup_shim: Any = _NoopShim()
    live_shim: Any = (
        _ContainerShimDispatcher(session_factory, app.state.settings.shim_port)
        if docker_client is not None
        else _NoopShim()
    )

    if docker_client is not None:
        # spec §4.11: reconcile BEFORE the public listener accepts traffic.
        try:
            async with session_factory() as db:
                await reconcile_all(db, docker_client, startup_shim, settings=app.state.settings)
        except Exception:  # noqa: BLE001
            log.exception("startup reconcile failed; continuing startup")

    shim: Any = live_shim

    # Store docker client on app state so background tasks can share it.
    app.state.docker_client = docker_client
    app.state.shim = shim

    # Launch background sweep tasks.
    bg: list[asyncio.Task[None]] = []
    if docker_client is not None:
        bg.append(
            asyncio.create_task(
                _bg_loop(session_factory, docker_client, shim, periodic_sweep,
                         interval=_RECONCILE_INTERVAL,
                         fn_kwargs={"settings": app.state.settings}),
                name="reconciler-sweep",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(session_factory, docker_client, shim, idle_pause_sweep,
                         interval=_IDLE_PAUSE_SWEEP_INTERVAL),
                name="idle-pause-sweep",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(session_factory, docker_client, shim, archive_sweep,
                         interval=_ARCHIVE_SWEEP_INTERVAL),
                name="archive-sweep",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(session_factory, docker_client, shim, reclaim_sweep,
                         interval=_RECLAIM_SWEEP_INTERVAL),
                name="reclaim-sweep",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(session_factory, docker_client, shim, volume_size_sweep,
                         interval=_VOLUME_CHECK_INTERVAL_SECONDS),
                name="volume-size-check",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(
                    session_factory, docker_client, shim, scheduler_sweep,
                    interval=_SCHEDULER_INTERVAL,
                    fn_kwargs={
                        "settings": app.state.settings,
                        "session_factory": session_factory,
                    },
                ),
                name="scheduler-sweep",
            )
        )

    from control_plane.auth.crypto import load_key_from_env
    from control_plane.oauth_service import oauth_connection_sweep, oauth_poll_sweep

    try:
        _oauth_master = load_key_from_env()
    except Exception:  # noqa: BLE001 — no key configured → subscription auth disabled
        _oauth_master = None
    if _oauth_master is not None:
        bg.append(
            asyncio.create_task(
                _bg_loop(
                    session_factory, docker_client, shim, oauth_poll_sweep,
                    interval=app.state.settings.oauth_poll_sweep_interval_seconds,
                    fn_kwargs={
                        "settings": app.state.settings,
                        "master_key": _oauth_master,
                        "event_bus": app.state.oauth_events,
                    },
                ),
                name="oauth-poll-sweep",
            )
        )
        bg.append(
            asyncio.create_task(
                _bg_loop(
                    session_factory, docker_client, shim, oauth_connection_sweep,
                    interval=app.state.settings.oauth_connection_sweep_interval_seconds,
                ),
                name="oauth-connection-sweep",
            )
        )

    app.state.bg_tasks = bg

    yield  # uvicorn opens the listener socket here; reconcile has already finished

    # Graceful shutdown: cancel background tasks.
    for task in bg:
        task.cancel()
    if bg:
        await asyncio.gather(*bg, return_exceptions=True)

    if docker_client is not None:
        try:
            docker_client.close()
        except Exception:  # noqa: BLE001
            pass


def create_app(settings: Settings) -> FastAPI:
    setup_logging()
    # Serve the OpenAPI docs under /v1 so they sit behind the same path prefix
    # the dev Vite proxy and prod Traefik already forward to this service; the
    # SPA owns every other path and would otherwise swallow /docs.
    app = FastAPI(
        title="agent-runtime control plane",
        lifespan=_lifespan,
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    from control_plane.model_catalog import load_catalog
    from control_plane.oauth_events import OAuthEventBus
    app.state.oauth_events = OAuthEventBus()
    app.state.model_catalog = load_catalog()

    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]

    # FastAPI's default 422 handler echoes the request body under
    # detail[].input, which would leak secret fields (git PATs, credentials).
    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,  # type: ignore[arg-type]
    )

    async def _internal_error_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "internal server error"}},
        )

    app.add_exception_handler(Exception, _internal_error_handler)

    # Health endpoint: SELECT 1 -> 200/503 (spec §12).
    app.include_router(health_router.router)

    # Core resource routers.
    app.include_router(models_router, prefix="/v1")
    app.include_router(templates_router, prefix="/v1")
    app.include_router(skills_router, prefix="/v1")
    app.include_router(mcp_servers_router, prefix="/v1")
    app.include_router(prompts_router, prefix="/v1")
    app.include_router(workflows_router, prefix="/v1")
    app.include_router(containers_router, prefix="/v1")
    app.include_router(images_router, prefix="/v1")
    app.include_router(tasks_router, prefix="/v1")
    app.include_router(scheduled_tasks_router, prefix="/v1")
    app.include_router(files_router, prefix="/v1")
    app.include_router(console_router, prefix="/v1")
    app.include_router(git_router, prefix="/v1")
    app.include_router(analytics_router, prefix="/v1")

    # Account and administration routers.
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(tenants_router.router)
    app.include_router(api_keys_router.router)
    app.include_router(credentials_router.router)
    app.include_router(admin_router.router)

    return app
