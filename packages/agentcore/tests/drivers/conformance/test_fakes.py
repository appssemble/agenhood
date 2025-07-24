import asyncio

import pytest

from tests.drivers.conformance import fakes

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_fakeproc_replays_lines_and_patch_returns_proc(monkeypatch):
    proc = fakes.FakeProc(['{"a":1}\n', '{"b":2}\n'], returncode=0)
    fakes.patch_proc(monkeypatch, proc)
    import agentcore.sandbox as sandbox

    got = await sandbox.spawn_untrusted(["x"], cwd="/", env={})
    assert got is proc
    assert await proc.stdout.readline() == b'{"a":1}\n'
    assert await proc.stdout.readline() == b'{"b":2}\n'
    assert await proc.stdout.readline() == b""


def test_collector_captures_events():
    events, emit = fakes.collector()
    asyncio.run(emit("status_change", {"to": "running"}))
    assert events == [("status_change", {"to": "running"})]


def test_subs_maps_workspace_and_secrets():
    subs = fakes.SUBS("/tmp/ws123")
    assert subs["/tmp/ws123"] == "<WS>"
    assert subs[fakes.CRED] == "<CRED>"
