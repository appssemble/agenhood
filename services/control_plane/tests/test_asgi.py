from __future__ import annotations

import pytest


@pytest.mark.unit
def test_asgi_exposes_module_level_app() -> None:
    from control_plane.asgi import app

    # FastAPI app built from env defaults, importable without a DB connection.
    assert app.title == "agent-runtime control plane"
    # The health route is mounted. FastAPI includes routers lazily (via
    # _IncludedRouter wrappers), so app.routes no longer surfaces included
    # paths through `.path`; the OpenAPI schema resolves them.
    assert "/healthz" in app.openapi()["paths"]
