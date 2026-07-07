from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.containers as containers_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed", seed_api_key="tk_live_seed", seed_llm_api_key="",
    agent_image_tag="test", internal_network="test",
    readyz_timeout_seconds=1.0, shim_port=8080,
)
_APP = create_app(_SETTINGS)
TENANT_ID = "ten_1"
CONTAINER_ID = "ctr_test_1"
_PRINCIPAL = Principal(tenant_id=TENANT_ID, role="member", is_staff=False, user_id="usr_1")


def _make_client() -> TestClient:
    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


def test_empty_body_rejected_before_touching_db_or_docker() -> None:
    """Neither mem_limit nor cpus supplied → 400, checked before any DB/lifecycle
    work (so this test needs no session/docker fixtures at all — matches the
    'pure pre-docker guard' scope of test_container_routes_lifecycle.py)."""
    client = _make_client()
    r = client.patch(f"/v1/containers/{CONTAINER_ID}/resources", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
