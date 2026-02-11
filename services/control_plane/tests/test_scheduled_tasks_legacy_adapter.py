"""Tests for legacy container-scoped scheduled-task compatibility adapters (unit).

Covers the thin adapters added on the old /v1/containers/{cid}/scheduled-tasks*
paths that were dropped when Task 18 moved scheduled tasks to tenant-scoped routes.

Uses the same ScriptedSession pattern as tests/test_scheduled_tasks_router.py.
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


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _use(session_factory: Any) -> None:
    app.dependency_overrides[resolve_principal] = lambda: ADMIN
    app.state.session_factory = session_factory


def test_legacy_get_redirects_308() -> None:
    """GET /v1/containers/{cid}/scheduled-tasks → 308 redirect to /v1/scheduled-tasks."""
    _use(lambda: ScriptedSession())
    with TestClient(app, follow_redirects=False) as c:
        r = c.get("/v1/containers/con_abc/scheduled-tasks")
    assert r.status_code == 308
    assert r.headers["location"] == "/v1/scheduled-tasks"


def test_legacy_post_translates_and_warns() -> None:
    """POST old body → prompt-target schedule created + Deprecation header present.

    DB call order inside a single session:
      1. dup-check: SELECT id FROM prompts WHERE tenant_id=... AND name=...  → []
      2. prompt INSERT                                                         → None
      3. _assert_target_exists prompt check                                    → ("prm_x",)
      4. _assert_target_exists container check                                 → ("con_abc",)
      (schedule INSERT + commit need no scripted rows)
    """
    _use(
        lambda: ScriptedSession(
            query_results=[
                [],           # 1. dup-check: no existing prompt with that name
                None,         # 2. prompt INSERT
                ("prm_x",),   # 3. prompt exists in tenant
                ("con_abc",), # 4. container exists in tenant
            ]
        )
    )
    with TestClient(app, follow_redirects=False) as c:
        r = c.post(
            "/v1/containers/con_abc/scheduled-tasks",
            json={
                "name": "daily sync",
                "task_body": {"prompt": "Do the sync task"},
                "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 200, r.text
    assert r.headers.get("deprecation") == "true"
    body = r.json()
    assert body["target"]["kind"] == "prompt"


def test_legacy_patch_translates_and_warns() -> None:
    """PATCH old body with task_body → new ad-hoc prompt and deprecation header.

    DB call order inside a single session:
      1. _load_owned_schedule: SELECT from scheduled_tasks → existing row
      2. dup-check: SELECT id FROM prompts WHERE tenant_id=... AND name=...  → []
      3. prompt INSERT                                                         → None
      4. _assert_target_exists prompt check                                    → ("prm_y",)
      5. _assert_target_exists container check                                 → ("con_abc",)
      (_do_update_scheduled_task UPDATE + commit need no scripted rows)
    """
    _existing_row = {
        "id": "st_existing",
        "tenant_id": "ten_1",
        "name": "old sync",
        "target": {
            "kind": "prompt",
            "container_id": "con_abc",
            "prompt_id": "prm_old",
            "variables": {},
        },
        "schedule": {"kind": "recurring", "unit": "day", "time": "09:00"},
        "timezone": "UTC",
        "enabled": True,
        "next_run_at": None,
        "last_run_at": None,
        "last_run_ref": None,
        "last_status": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    _use(
        lambda: ScriptedSession(
            query_results=[
                [_existing_row],  # 1. load existing scheduled task row
                [],               # 2. dup-check: no existing prompt with that name
                None,             # 3. prompt INSERT
                ("prm_y",),       # 4. prompt exists in tenant
                ("con_abc",),     # 5. container exists in tenant
            ]
        )
    )
    with TestClient(app, follow_redirects=False) as c:
        r = c.patch(
            "/v1/containers/con_abc/scheduled-tasks/st_existing",
            json={
                "task_body": {"prompt": "Updated task body"},
                "schedule": {"kind": "recurring", "unit": "day", "time": "10:00"},
                "timezone": "UTC",
            },
        )
    assert r.status_code == 200, r.text
    assert r.headers.get("deprecation") == "true"
    body = r.json()
    assert body["target"]["kind"] == "prompt"
