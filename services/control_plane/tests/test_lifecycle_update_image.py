from __future__ import annotations

import pytest

import control_plane.docker_ctl.provision as provision
import control_plane.lifecycle as lc
from control_plane.errors import APIError

pytestmark = pytest.mark.unit


@pytest.fixture
def recorder(monkeypatch):
    calls: list[tuple] = []

    async def fake_set(db, cid, **fields):
        calls.append(("set", fields))

    async def fake_destroy(db, dc, shim, cid, **kw):
        calls.append(("destroy", cid))
        return True

    async def fake_restore(db, dc, shim, cid, tid, **kw):
        calls.append(("restore", cid))

    def fake_pull(client, settings, image_tag, *, force=False):
        calls.append(("pull", image_tag, force))
        return f"agent-runtime:{image_tag}"

    async def fake_audit(db, *, actor_type, action, actor_id=None, target_type=None, target_id=None, details=None):
        calls.append(("audit", action, details))

    monkeypatch.setattr(lc, "_set", fake_set)
    monkeypatch.setattr(lc, "destroy", fake_destroy)
    monkeypatch.setattr(lc, "restore", fake_restore)
    monkeypatch.setattr(provision, "pull_or_verify_image", fake_pull)
    monkeypatch.setattr(lc, "audit", fake_audit)
    return calls


@pytest.mark.asyncio
async def test_running_pulls_then_recreates(recorder, monkeypatch):
    async def status(db, cid):
        return "running"

    monkeypatch.setattr(lc, "current_status", status)
    await lc.update_image(None, object(), object(), "ctr_1", "ten_1", "v2", limit=5, settings=object())
    assert [c[0] for c in recorder] == ["pull", "set", "audit", "destroy", "restore"]
    audit_call = next(c for c in recorder if c[0] == "audit")
    assert audit_call[1] == "container.update_image"
    assert audit_call[2] == {"image_tag": "v2"}


@pytest.mark.asyncio
async def test_archived_only_sets_tag(recorder, monkeypatch):
    async def status(db, cid):
        return "archived"

    monkeypatch.setattr(lc, "current_status", status)
    await lc.update_image(None, object(), object(), "ctr_1", "ten_1", "v2", limit=5, settings=object())
    assert [c[0] for c in recorder] == ["pull", "set", "audit"]  # no destroy/restore
    audit_call = next(c for c in recorder if c[0] == "audit")
    assert audit_call[1] == "container.update_image"
    assert audit_call[2] == {"image_tag": "v2"}


@pytest.mark.asyncio
async def test_update_image_forces_pull(recorder, monkeypatch):
    async def status(db, cid):
        return "running"

    monkeypatch.setattr(lc, "current_status", status)
    await lc.update_image(None, object(), object(), "ctr_1", "ten_1", "v2", limit=5, settings=object())
    pull_call = next(c for c in recorder if c[0] == "pull")
    assert pull_call == ("pull", "v2", True)


@pytest.mark.asyncio
async def test_invalid_state_409(recorder, monkeypatch):
    async def status(db, cid):
        return "provisioning"

    monkeypatch.setattr(lc, "current_status", status)
    with pytest.raises(APIError) as ei:
        await lc.update_image(None, object(), object(), "ctr_1", "ten_1", "v2", limit=5, settings=object())
    assert ei.value.status_code == 409
    assert recorder == []  # nothing pulled or changed


@pytest.mark.asyncio
async def test_pull_failure_no_teardown(monkeypatch):
    calls: list[tuple] = []

    async def status(db, cid):
        return "running"

    async def fake_destroy(db, dc, shim, cid, **kw):
        calls.append(("destroy", cid))

    def fail_pull(client, settings, image_tag, *, force=False):
        raise provision.ImageUnavailable("nope")

    monkeypatch.setattr(lc, "current_status", status)
    monkeypatch.setattr(lc, "destroy", fake_destroy)
    monkeypatch.setattr(provision, "pull_or_verify_image", fail_pull)
    with pytest.raises(APIError) as ei:
        await lc.update_image(None, object(), object(), "ctr_1", "ten_1", "bad", limit=5, settings=object())
    assert ei.value.status_code == 422
    assert calls == []  # never torn down
