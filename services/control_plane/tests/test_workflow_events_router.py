from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.workflows as wf
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


def _event_row(seq: int, type_: str, payload: dict[str, Any]) -> Any:
    import datetime as _dt

    class _R:
        pass

    r = _R()
    r.seq = seq
    r.type = type_
    r.payload = payload
    r.ts = _dt.datetime(2026, 6, 29, tzinfo=_dt.UTC)
    return r


def test_json_history_filters_after_seq(monkeypatch):
    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_owned(session, tid, wid):
        return {"id": wid}

    async def fake_load_run(session, tid, rid):
        return {"id": rid, "workflow_id": "wf_1", "tenant_id": tid}

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_owned)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)

    rows = [
        _event_row(1, "started", {"step": 0}),
        _event_row(2, "completed", {"step_count": 1}),
    ]

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            class _Res:
                def all(self_inner):
                    return rows
            return _Res()

    app.state.session_factory = lambda: _Sess()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_1/events?after_seq=1")
    assert r.status_code == 200
    seqs = [e["seq"] for e in r.json()["events"]]
    assert seqs == [2]


def test_run_not_found_returns_404(monkeypatch):
    app.dependency_overrides[resolve_principal] = lambda: ADMIN

    async def fake_owned(session, tid, wid):
        return {"id": wid}

    async def fake_load_run(session, tid, rid):
        return None  # not owned by this tenant

    monkeypatch.setattr(wf, "_load_owned_workflow", fake_owned)
    monkeypatch.setattr(wf, "_load_run", fake_load_run)

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            class _Res:
                def all(self_inner):
                    return []
            return _Res()

    app.state.session_factory = lambda: _Sess()

    with TestClient(app) as c:
        r = c.get("/v1/workflows/wf_1/runs/wfr_missing/events")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_generator_drains_then_closes_on_terminal():
    # Two scripted poll batches: backlog (started), then (completed) -> stop.
    batches = [
        [_event_row(1, "started", {"step": 0})],
        [_event_row(2, "completed", {"step_count": 1})],
    ]

    def make_factory():
        calls = {"n": 0}

        class _Sess:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, *a, **k):
                idx = calls["n"]
                calls["n"] += 1
                batch = batches[idx] if idx < len(batches) else []

                class _Res:
                    def all(self_inner):
                        return batch
                return _Res()

        return lambda: _Sess()

    async def never_disconnected():
        return False

    frames = []
    gen = wf._workflow_events_stream(
        make_factory(), "wfr_1", None, never_disconnected, poll_interval=0,
    )
    async for frame in gen:
        frames.append(frame)
        if len(frames) > 5:  # safety against a non-terminating generator
            break

    assert len(frames) == 2
    assert '"type": "started"' in frames[0]
    assert '"type": "completed"' in frames[1]
