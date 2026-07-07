from __future__ import annotations

import pytest

import control_plane.lifecycle as lc
from control_plane.errors import APIError

pytestmark = pytest.mark.unit


@pytest.fixture
def recorder(monkeypatch):
    calls: list[tuple] = []

    async def fake_load(db, cid):
        calls.append(("load", cid))
        return {"docker_name": "agent-x", "mem_limit": "4g", "cpus": 2.0}

    async def fake_set(db, cid, **fields):
        calls.append(("set", fields))

    async def fake_update_resources(client, docker_name, mem_limit, cpus):
        calls.append(("docker_update", docker_name, mem_limit, cpus))

    async def fake_resume(db, dc, cid, *, settings=None):
        calls.append(("resume", cid))

    async def fake_audit(
        db, *, actor_type, action, actor_id=None, target_type=None, target_id=None, details=None
    ):
        calls.append(("audit", action, details))

    monkeypatch.setattr(lc, "_load", fake_load)
    monkeypatch.setattr(lc, "_set", fake_set)
    monkeypatch.setattr(lc.docker_ctl, "update_resources", fake_update_resources)
    monkeypatch.setattr(lc, "resume", fake_resume)
    monkeypatch.setattr(lc, "audit", fake_audit)
    return calls


@pytest.mark.asyncio
async def test_running_live_updates_no_resume(recorder, monkeypatch):
    async def status(db, cid):
        return "running"

    monkeypatch.setattr(lc, "current_status", status)
    result = await lc.update_resources(None, object(), "ctr_1", mem_limit="2g", cpus=1.0)
    assert result == "running"
    assert [c[0] for c in recorder] == ["load", "docker_update", "set", "audit"]
    audit_call = next(c for c in recorder if c[0] == "audit")
    assert audit_call[1] == "container.update_resources"
    assert audit_call[2] == {
        "mem_limit": "2g", "cpus": 1.0,
        "previous_mem_limit": "4g", "previous_cpus": 2.0,
    }


@pytest.mark.asyncio
async def test_paused_updates_then_resumes(recorder, monkeypatch):
    async def status(db, cid):
        return "paused"

    monkeypatch.setattr(lc, "current_status", status)
    result = await lc.update_resources(None, object(), "ctr_1", mem_limit="2g", cpus=1.0)
    assert result == "running"
    assert [c[0] for c in recorder] == ["load", "docker_update", "set", "audit", "resume"]


@pytest.mark.asyncio
async def test_archived_persists_only(recorder, monkeypatch):
    async def status(db, cid):
        return "archived"

    monkeypatch.setattr(lc, "current_status", status)
    result = await lc.update_resources(None, object(), "ctr_1", mem_limit="2g", cpus=1.0)
    assert result == "archived"
    assert [c[0] for c in recorder] == ["load", "set", "audit"]  # no docker_update, no resume


@pytest.mark.asyncio
async def test_invalid_state_409(recorder, monkeypatch):
    async def status(db, cid):
        return "provisioning"

    monkeypatch.setattr(lc, "current_status", status)
    with pytest.raises(APIError) as ei:
        await lc.update_resources(None, object(), "ctr_1", mem_limit="2g", cpus=1.0)
    assert ei.value.status_code == 409
    assert ei.value.code == "container_not_updatable"
    assert recorder == []


@pytest.mark.asyncio
async def test_docker_failure_surfaces_as_503(recorder, monkeypatch):
    """Design doc §8: a daemon-level failure (e.g. the container vanished between
    _load and the update call) must surface as 503, matching how ReadinessFailed
    is surfaced during create — not an unhandled 500."""
    import docker.errors

    async def status(db, cid):
        return "running"

    async def failing_update_resources(client, docker_name, mem_limit, cpus):
        raise docker.errors.NotFound("container gone")

    monkeypatch.setattr(lc, "current_status", status)
    monkeypatch.setattr(lc.docker_ctl, "update_resources", failing_update_resources)
    with pytest.raises(APIError) as ei:
        await lc.update_resources(None, object(), "ctr_1", mem_limit="2g", cpus=1.0)
    assert ei.value.status_code == 503
    assert ei.value.code == "container_not_runnable"
    # Never persisted or audited a change that never actually applied.
    assert [c[0] for c in recorder if c[0] in ("set", "audit")] == []
