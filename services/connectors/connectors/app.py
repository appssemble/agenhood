from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from connectors.config import Settings
from connectors.cp_client import ControlPlaneClient
from connectors.db import make_engine, make_session_factory
from connectors.errors import APIError, api_error_handler
from connectors.providers.github import GitHubProvider
from connectors.providers.slack import SlackProvider
from connectors.routers import bindings as bindings_router
from connectors.routers import connections as connections_router
from connectors.routers import health
from connectors.routers import oauth as oauth_router
from connectors.routers import routing_rules as routing_rules_router
from connectors.routers import webhooks as webhooks_router


@asynccontextmanager
async def _lifespan(app: FastAPI) -> Any:
    if getattr(app.state, "start_background", False):
        from connectors.resume import resume_open_deliveries
        # I4: schedule resume as a detached task so startup is not blocked
        # and a slow/failing resume doesn't delay the first request.
        asyncio.create_task(resume_open_deliveries(
            factory=app.state.session_factory, providers=app.state.providers,
            cp_client=app.state.cp_client, master_key=app.state.master_key,
            coalesce_ms=app.state.settings.relay_coalesce_ms,
        ))
    yield


def create_app(*, start_background: bool = True) -> FastAPI:
    app = FastAPI(title="connectors", lifespan=_lifespan)
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.include_router(health.router)
    app.include_router(connections_router.router)
    app.include_router(bindings_router.router)
    app.include_router(routing_rules_router.router)
    app.include_router(oauth_router.router)

    # Master encryption key
    if settings.master_key_b64:
        app.state.master_key = base64.b64decode(settings.master_key_b64)
    else:
        app.state.master_key = b"\x00" * 32  # dev only; real key required in prod

    # Provider registry
    providers: dict[str, Any] = {}
    if settings.slack_signing_secret:
        providers["slack"] = SlackProvider(
            signing_secret=settings.slack_signing_secret,
            client_id=settings.slack_client_id or "",
            client_secret=settings.slack_client_secret or "",
        )
    if settings.github_app_id:
        providers["github"] = GitHubProvider(
            app_id=settings.github_app_id,
            private_key_pem=settings.github_app_private_key or "",
            webhook_secret=settings.github_webhook_secret or "",
        )
    app.state.providers = providers
    app.state.cp_client = ControlPlaneClient(base_url=settings.control_plane_base_url)
    app.include_router(webhooks_router.router)

    app.state.start_background = start_background
    return app
