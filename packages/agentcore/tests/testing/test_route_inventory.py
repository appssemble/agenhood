from __future__ import annotations

import pytest
from fastapi import FastAPI

from agentcore.testing.route_inventory import assert_routes_covered, collect_routes

pytestmark = pytest.mark.unit


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/covered")
    def covered() -> dict:
        return {}

    @app.post("/uncovered")
    def uncovered() -> dict:
        return {}

    return app


def test_collect_ignores_framework_defaults():
    routes = collect_routes(_app())
    assert ("GET", "/covered") in routes
    assert ("POST", "/uncovered") in routes
    # openapi/docs/redoc are never reported
    assert not any(p in {"/openapi.json", "/docs", "/redoc"} for _, p in routes)
    # auto HEAD/OPTIONS are never reported
    assert not any(m in {"HEAD", "OPTIONS"} for m, _ in routes)


def test_gate_catches_untested_route():
    with pytest.raises(AssertionError) as ei:
        assert_routes_covered(_app(), tested_paths=[("GET", "/covered")])
    assert "/uncovered" in str(ei.value)


def test_gate_passes_when_all_tested():
    assert_routes_covered(
        _app(), tested_paths=[("GET", "/covered"), ("POST", "/uncovered")]
    )


def test_allow_list_suppresses_reviewed_gap():
    assert_routes_covered(
        _app(),
        tested_paths=[("GET", "/covered")],
        allow=[("POST", "/uncovered")],
    )


def test_stale_allow_entry_is_rejected():
    with pytest.raises(AssertionError) as ei:
        assert_routes_covered(
            _app(),
            tested_paths=[("GET", "/covered"), ("POST", "/uncovered")],
            allow=[("GET", "/ghost")],
        )
    assert "stale" in str(ei.value).lower()


def test_include_router_routes_are_found():
    """Regression: the lazy _IncludedRouter recursion branch in _walk must be
    exercised. Under FastAPI 0.138 app.include_router() may produce an
    _IncludedRouter in app.routes whose children live at .original_router.routes,
    not .routes. If that branch is removed, this test fails and CI catches it."""
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/widgets/{id}")
    def get_widget(id: int) -> dict:
        return {}

    app = FastAPI()
    app.include_router(router, prefix="/v1")

    routes = collect_routes(app)
    assert ("GET", "/v1/widgets/{id}") in routes
