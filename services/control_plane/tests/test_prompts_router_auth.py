"""Prompts router HTTP-path tests (unit; no DB). Mirrors test_mcp_router_auth.py."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)
app = create_app(_SETTINGS)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        return None


def _override_principal() -> None:
    app.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id="ten_seed", user_id="usr_1", role="member", is_staff=False,
    )


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_list_prompts_empty_ok() -> None:
    _override_principal()
    app.state.session_factory = lambda: _FakeSession([])
    client = TestClient(app)
    r = client.get("/v1/prompts")
    assert r.status_code == 200
    assert r.json() == {"prompts": []}


def test_create_prompt_returns_view_without_tenant_id() -> None:
    _override_principal()
    app.state.session_factory = lambda: _FakeSession([])  # no dupe row
    client = TestClient(app)
    r = client.post("/v1/prompts", json={"name": "Weekly", "body": "Hi {{team}}"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Weekly"
    assert "tenant_id" not in data
    assert [v["name"] for v in data["variables"]] == ["team"]


def test_create_rejects_blank_body() -> None:
    _override_principal()
    app.state.session_factory = lambda: _FakeSession([])
    client = TestClient(app)
    r = client.post("/v1/prompts", json={"name": "Weekly", "body": ""})
    assert r.status_code == 400
    assert r.json()["error"]["field"] == "body"
