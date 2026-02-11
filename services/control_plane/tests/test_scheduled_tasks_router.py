"""Tenant-scoped scheduled-tasks router validation branches (unit; fake session).

Exercises the create-path on /v1/scheduled-tasks: prompt/workflow targets,
bad target rejection, and bad timezone rejection. Uses the create_app +
dependency_overrides[resolve_principal] + ScriptedSession pattern from
tests/test_workflows_router.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from scripted_db import ScriptedSession

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
ADMIN = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _use(session_factory) -> None:
    app.dependency_overrides[resolve_principal] = lambda: ADMIN
    app.state.session_factory = session_factory


def test_create_prompt_target_ok():
    # Existence checks: prompt row found, container row found.
    _use(lambda: ScriptedSession(query_results=[("prm_1",), ("con_1",)]))
    with TestClient(app) as c:
        r = c.post(
            "/v1/scheduled-tasks",
            json={
                "name": "daily",
                "target": {
                    "kind": "prompt",
                    "container_id": "con_1",
                    "prompt_id": "prm_1",
                    "variables": {"x": "1"},
                },
                "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "daily"
    assert body["target"]["kind"] == "prompt"
    assert body["target"]["prompt_id"] == "prm_1"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None
    # New shape never exposes the dropped columns.
    for gone in ("container_id", "driver", "model", "task_body", "last_task_id"):
        assert gone not in body


def test_create_workflow_target_ok():
    # Existence check: workflow row found.
    _use(lambda: ScriptedSession(query_results=[("wf_1",)]))
    with TestClient(app) as c:
        r = c.post(
            "/v1/scheduled-tasks",
            json={
                "name": "wf nightly",
                "target": {"kind": "workflow", "workflow_id": "wf_1"},
                "schedule": {"kind": "recurring", "unit": "day", "time": "02:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == {"kind": "workflow", "workflow_id": "wf_1"}
    assert body["next_run_at"] is not None


def test_create_rejects_bad_target():
    _use(lambda: ScriptedSession())
    with TestClient(app) as c:
        r = c.post(
            "/v1/scheduled-tasks",
            json={
                "name": "bad",
                "target": {"kind": "nonsense"},
                "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["field"] == "target"


def test_create_rejects_unknown_prompt():
    # Prompt existence check returns no rows → 400 field target.
    _use(lambda: ScriptedSession(query_results=[[]]))
    with TestClient(app) as c:
        r = c.post(
            "/v1/scheduled-tasks",
            json={
                "name": "daily",
                "target": {
                    "kind": "prompt",
                    "container_id": "con_1",
                    "prompt_id": "prm_missing",
                },
                "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["field"] == "target"


def test_create_rejects_bad_timezone():
    _use(lambda: ScriptedSession())
    with TestClient(app) as c:
        r = c.post(
            "/v1/scheduled-tasks",
            json={
                "name": "daily",
                "target": {
                    "kind": "prompt",
                    "container_id": "con_1",
                    "prompt_id": "prm_1",
                },
                "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
                "timezone": "Not/AZone",
            },
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
