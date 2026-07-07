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
from control_plane.routers.deploy_keys import router as deploy_keys_router
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


_API_DESCRIPTION = """\
The **control plane** is the public REST + SSE API for Agenhood. Everything the
console does is available here — the console is just one client.

### Agents are containers

An *agent* is a long-lived, isolated **container** with its own workspace,
configuration, and git state. You provision a container, PATCH its config, then
submit **tasks** to it. Most task, file, git, and console routes are scoped under
`/v1/containers/{cid}/…`.

### Base path

Every endpoint is served under the **`/v1`** prefix (account/admin routes carry
their own prefixes, e.g. `/v1/auth`, `/admin/v1`). The same origin serves the
console, so in production the API lives beside the SPA under `/v1`.

### Authentication

Send an API key or session token as a **bearer token**:

```
Authorization: Bearer tk_live_xxx
```

API keys are tenant-scoped (`tk_live_…`); the console uses a session cookie.
Admin routes (`/admin/v1`) require a staff or admin-role principal.

### Streaming

Live feeds — task events, workflow run events, OAuth connection status — are
served as **Server-Sent Events** (`text/event-stream`). Open them with a
streaming client (`curl -N`, `EventSource`) rather than a normal JSON fetch.

### Errors

Errors return a JSON envelope with a stable machine-readable `code`:

```json
{ "error": { "code": "not_found", "message": "container … not found" } }
```

Request-validation failures (422) instead return `{ "detail": [ … ] }` with the
offending field locations (request bodies are never echoed back, to avoid
leaking secrets).
"""

# Tag metadata drives grouping, ordering, and per-group descriptions in the
# Swagger/ReDoc UIs. Each router sets a matching ``tags=[…]`` on its APIRouter;
# the canonical tag name for each router is the ``name`` below.
_OPENAPI_TAGS = [
    {
        "name": "Containers",
        "description": (
            "Provision, configure, and manage the lifecycle of agent containers "
            "(create, pause, resume, destroy, restore, resize, update image)."
        ),
    },
    {
        "name": "Tasks",
        "description": (
            "Submit prompts to a container, list tasks and sessions, cancel runs, "
            "and stream live task events."
        ),
    },
    {
        "name": "Scheduled Tasks",
        "description": (
            "Cron- and one-shot schedules that fire a prompt or workflow against a container."
        ),
    },
    {
        "name": "Workflows",
        "description": (
            "Multi-step prompt pipelines, their runs, and live run-event streams."
        ),
    },
    {
        "name": "Files",
        "description": (
            "Browse, read, write, delete, and archive files inside a container's workspace."
        ),
    },
    {"name": "Console", "description": "Interactive shell access to a container over a WebSocket."},
    {
        "name": "Git",
        "description": (
            "Workspace git state — snapshots, remotes, push, rollback, and repo linking."
        ),
    },
    {
        "name": "Skills",
        "description": (
            "Reusable agent skills sourced from git refs, attachable to a container's config."
        ),
    },
    {
        "name": "MCP Servers",
        "description": "Model Context Protocol server definitions available to agents.",
    },
    {"name": "Prompts", "description": "Saved, reusable prompt templates."},
    {
        "name": "Templates",
        "description": "Reusable container configurations used to seed new agents.",
    },
    {"name": "Models", "description": "The catalog of LLM models available for agent configs."},
    {"name": "Images", "description": "Available agent container image tags."},
    {"name": "Analytics", "description": "Token- and task-usage time series and breakdowns."},
    {"name": "Auth", "description": "Login, logout, tenant selection, and the current principal."},
    {"name": "Users", "description": "Manage users within a tenant."},
    {"name": "Tenants", "description": "Tenant self-service operations."},
    {"name": "API Keys", "description": "Create, list, and revoke tenant API keys."},
    {
        "name": "Credentials",
        "description": (
            "LLM provider credentials and subscription OAuth connection flows."
        ),
    },
    {
        "name": "Admin",
        "description": (
            "Staff-only administration of tenants, users, and platform health."
        ),
    },
    {"name": "Health", "description": "Liveness and readiness probes."},
]


def create_app(settings: Settings) -> FastAPI:
    setup_logging()
    # Serve the OpenAPI docs under /v1 so they sit behind the same path prefix
    # the dev Vite proxy and prod Traefik already forward to this service; the
    # SPA owns every other path and would otherwise swallow /docs.
    app = FastAPI(
        title="agent-runtime control plane",
        description=_API_DESCRIPTION,
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
        openapi_tags=_OPENAPI_TAGS,
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
    app.include_router(deploy_keys_router, prefix="/v1")
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
