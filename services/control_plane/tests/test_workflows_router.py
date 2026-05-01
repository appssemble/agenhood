"""Workflows router validation branches (unit; fake session, no DB).

Exercises CRUD validation, /run happy path (monkeypatched start_run),
and the start_run failure handling.
"""
from __future__ import annotations

from typing import Any

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


def _wf_row() -> dict[str, Any]:
    return {
        "id": "wf_1",
        "tenant_id": "ten_1",
        "name": "W",
        "description": None,
        "steps": [{"prompt_id": "prm_1", "container_id": "con_1", "variables": {}}],
        "created_by": None,
        "created_at": None,
        "updated_at": None,
    }


def teardown_function() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def test_create_rejects_empty_steps():
    app.dependency_overrides[resolve_principal] = lambda: ADMIN
    with TestClient(app) as c:
        r = c.post("/v1/workflows", json={"name": "W", "steps": []})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["field"] == "steps"


def test_create_rejects_unknown_prompt():
    """If the prompt doesn't exist in the tenant, return 400 with field 'steps'."""
    # Session returns: no matching prompts (empty), no containers needed
    app.dependency_overrides[resolve_principal] = lambda: ADMIN
    app.state.session_factory = lambda: ScriptedSession(
        query_results=[
            [],   # prompts existence check → no rows → missing prompt
        ]
    )
    with TestClient(app) as c:
        r = c.post(
            "/v1/workflows",
            json={
                "name": "W",
                "steps": [{"prompt_id": "prm_unknown", "container_id": "con_1", "variables": {}}],
            },
        )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["field"] == "steps"


# ---------------------------------------------------------------------------
# /run happy path
# ---------------------------------------------------------------------------

def test_run_returns_run_summary(monkeypatch):
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_start_run(session, **kw):
        return "wfr_1"

    monkeypatch.setattr(wf, "start_run", fake_start_run)

    async def fake_load_run(session, tenant_id, rid):
        return {
            "id": rid,
            "workflow_id": "wf_1",
            "status": "running",
            "cursor": 0,
            "step_count": 1,
            "current_task_id": "tsk_1",
            "error_step": None,
            "error_message": None,
            "trigger_source": "manual",
            "scheduled_task_id": None,
            "started_at": "2026-06-28T00:00:00+00:00",
            "ended_at": None,
        }

    monkeypatch.setattr(wf, "_load_run", fake_load_run)
    async def fake_load_owned_workflow(s, t, w):
        return _wf_row()

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow)

    app.state.session_factory = lambda: ScriptedSession()
    app.state.docker_client = None
    app.state.shim = None

    with TestClient(app) as c:
        r = c.post("/v1/workflows/wf_1/run", json={"trigger_source": "manual"})
    assert r.status_code == 200
    assert r.json()["status"] == "running"


# ---------------------------------------------------------------------------
# /run start failure handling
# ---------------------------------------------------------------------------

def test_run_start_failure_returns_clean_error(monkeypatch):
    """When start_run raises a non-APIError exception, the endpoint should return
    a clean JSON error envelope (not a 500 with stack trace)."""
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def failing_start_run(session, **kw):
        raise RuntimeError("container can't start: admission denied")

    monkeypatch.setattr(wf, "start_run", failing_start_run)

    async def fake_load_owned_workflow_fail(s, t, w):
        return _wf_row()

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow_fail)

    app.state.session_factory = lambda: ScriptedSession()
    app.state.docker_client = None
    app.state.shim = None

    with TestClient(app) as c:
        r = c.post("/v1/workflows/wf_1/run", json={"trigger_source": "manual"})

    # Should NOT be a 500; should be a clean error envelope
    assert r.status_code in (400, 502)
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "workflow_start_failed"
    assert "container can't start" in body["error"]["message"]


# ---------------------------------------------------------------------------
# GET /workflows/{wid}/runs/{run_id}  — run-detail endpoint
# ---------------------------------------------------------------------------

def test_get_run_detail_returns_ordered_steps(monkeypatch):
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_load_owned_workflow(s, t, w):
        return _wf_row()

    async def fake_load_run(session, tenant_id, rid):
        return {
            "id": rid, "workflow_id": "wf_1", "status": "running",
            "cursor": 1, "step_count": 2, "current_task_id": "tsk_1",
            "error_step": None, "error_message": None, "trigger_source": "manual",
            "scheduled_task_id": None,
            "started_at": "2026-06-29T09:00:00+00:00", "ended_at": None,
            "steps": [
                {"step_index": 0, "task_id": "tsk_0", "container_id": "con_1",
                 "status": "completed", "started_at": "2026-06-29T09:00:00+00:00",
                 "ended_at": "2026-06-29T09:00:48+00:00"},
                {"step_index": 1, "task_id": "tsk_1", "container_id": "con_2",
                 "status": "running", "started_at": "2026-06-29T09:00:48+00:00",
                 "ended_at": None},
            ],
        }

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)
    app.state.session_factory = lambda: ScriptedSession()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_9")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "wfr_9"
    assert [s["step_index"] for s in body["steps"]] == [0, 1]
    assert body["steps"][0]["status"] == "completed"
    assert body["steps"][1]["task_id"] == "tsk_1"


def test_get_run_detail_legacy_null_steps(monkeypatch):
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_load_owned_workflow(s, t, w):
        return _wf_row()

    async def fake_load_run(session, tenant_id, rid):
        return {
            "id": rid, "workflow_id": "wf_1", "status": "completed",
            "cursor": 1, "step_count": 2, "current_task_id": None,
            "error_step": None, "error_message": None, "trigger_source": "api",
            "scheduled_task_id": None,
            "started_at": "2026-06-29T09:00:00+00:00",
            "ended_at": "2026-06-29T09:04:00+00:00", "steps": None,
        }

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)
    app.state.session_factory = lambda: ScriptedSession()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_old")
    assert r.status_code == 200
    assert r.json()["steps"] is None


def test_get_run_detail_404_when_missing_or_other_workflow(monkeypatch):
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_load_owned_workflow(s, t, w):
        return _wf_row()

    async def fake_load_run(session, tenant_id, rid):
        return None  # not found

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)
    app.state.session_factory = lambda: ScriptedSession()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_missing")
    assert r.status_code == 404


def test_get_run_detail_404_when_run_belongs_to_other_workflow(monkeypatch):
    """Run exists but belongs to a different workflow; should return 404."""
    import control_plane.routers.workflows as wf

    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_load_owned_workflow(s, t, w):
        return _wf_row()

    async def fake_load_run(session, tenant_id, rid):
        return {
            "id": rid, "workflow_id": "wf_OTHER", "status": "running",
            "cursor": 0, "step_count": 1, "current_task_id": "tsk_1",
            "error_step": None, "error_message": None, "trigger_source": "manual",
            "scheduled_task_id": None,
            "started_at": "2026-06-29T09:00:00+00:00", "ended_at": None,
        }

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_load_owned_workflow)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)
    app.state.session_factory = lambda: ScriptedSession()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_x")
    assert r.status_code == 404
