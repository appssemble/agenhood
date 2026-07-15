"""transfer_step_exports unit tests with faked wake + shim client."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

import control_plane.workflow_transfer as wt
from control_plane.shim_client import ShimError, ShimExportUnmatched, ShimTransferTooLarge
from control_plane.workflow_transfer import WorkflowTransferError, transfer_step_exports

pytestmark = pytest.mark.unit


class _Settings:
    workflow_transfer_max_bytes = 1000


class _FakeShim:
    def __init__(self, log, name, *, manifest=None, manifest_exc=None,
                 import_result=None, import_exc=None):
        self._log = log
        self._name = name
        self._manifest = manifest or {"files": [{"path": "a", "size": 3}], "total_bytes": 3}
        self._manifest_exc = manifest_exc
        self._import_result = import_result or {"files_written": 1, "bytes_written": 3}
        self._import_exc = import_exc
        self.closed = False

    async def export_manifest(self, paths, *, max_bytes=None):
        self._log.append(("manifest", self._name, list(paths), max_bytes))
        if self._manifest_exc:
            raise self._manifest_exc
        return self._manifest

    async def export_stream(self, paths, *, max_bytes=None):
        self._log.append(("stream", self._name, list(paths), max_bytes))
        yield b"tar"

    async def import_archive(self, content, *, max_bytes=None):
        async for _ in content:
            pass
        self._log.append(("import", self._name, max_bytes))
        if self._import_exc:
            raise self._import_exc
        return self._import_result

    async def aclose(self):
        self.closed = True


def _wire(monkeypatch, shims):
    """shims: dict cid -> _FakeShim. Wires _wake to a no-op row and _shim_for
    to pick the fake for the row's cid."""
    async def fake_wake(session, *, settings, docker_client, shim_dispatcher,
                        tenant_id, cid):
        return {"cid": cid}

    monkeypatch.setattr(wt, "_wake", fake_wake)
    monkeypatch.setattr(wt, "_shim_for", lambda settings, row: shims[row["cid"]])


async def _call(exports=("out/**",), source="con_a", dest="con_b"):
    return await transfer_step_exports(
        object(), settings=_Settings(), docker_client=object(),
        shim_dispatcher=object(), tenant_id="ten_1",
        exports=list(exports), source_cid=source, dest_cid=dest,
    )


@pytest.mark.asyncio
async def test_cross_container_transfer_streams_and_reports(monkeypatch):
    log: list[Any] = []
    src = _FakeShim(log, "src")
    dst = _FakeShim(log, "dst", import_result={"files_written": 4, "bytes_written": 99})
    _wire(monkeypatch, {"con_a": src, "con_b": dst})

    out = await _call()

    assert out == {"files": 4, "bytes": 99}
    assert ("manifest", "src", ["out/**"], 1000) in log
    assert ("import", "dst", 1000) in log
    assert src.closed and dst.closed


@pytest.mark.asyncio
async def test_same_container_is_dry_run_only(monkeypatch):
    log: list[Any] = []
    src = _FakeShim(log, "src", manifest={"files": [{"path": "a", "size": 3},
                                                    {"path": "b", "size": 4}],
                                          "total_bytes": 7})
    _wire(monkeypatch, {"con_a": src})

    out = await _call(source="con_a", dest="con_a")

    assert out == {"files": 2, "bytes": 7}
    assert [op for op, *_ in log] == ["manifest"]  # no stream, no import
    assert src.closed


@pytest.mark.asyncio
async def test_unmatched_export_raises_specific_message(monkeypatch):
    log: list[Any] = []
    src = _FakeShim(log, "src", manifest_exc=ShimExportUnmatched(["dist/**"]))
    _wire(monkeypatch, {"con_a": src, "con_b": _FakeShim(log, "dst")})

    with pytest.raises(WorkflowTransferError, match=r"dist/\*\*"):
        await _call()


@pytest.mark.asyncio
async def test_too_large_raises(monkeypatch):
    log: list[Any] = []
    src = _FakeShim(log, "src", manifest_exc=ShimTransferTooLarge("413"))
    _wire(monkeypatch, {"con_a": src, "con_b": _FakeShim(log, "dst")})

    with pytest.raises(WorkflowTransferError, match="cap"):
        await _call()


@pytest.mark.asyncio
async def test_shim_error_wrapped(monkeypatch):
    log: list[Any] = []
    dst = _FakeShim(log, "dst", import_exc=ShimError("boom"))
    _wire(monkeypatch, {"con_a": _FakeShim(log, "src"), "con_b": dst})

    with pytest.raises(WorkflowTransferError, match="boom"):
        await _call()


@pytest.mark.asyncio
async def test_unexpected_error_wrapped(monkeypatch):
    log: list[Any] = []
    dst = _FakeShim(log, "dst", import_exc=RuntimeError("conn reset"))
    _wire(monkeypatch, {"con_a": _FakeShim(log, "src"), "con_b": dst})

    with pytest.raises(WorkflowTransferError, match="conn reset"):
        await _call()


@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch):
    log: list[Any] = []

    class _SlowShim(_FakeShim):
        async def export_manifest(self, paths, *, max_bytes=None):
            await asyncio.sleep(1)
            return {"files": [], "total_bytes": 0}

    _wire(monkeypatch, {"con_a": _SlowShim(log, "src"), "con_b": _FakeShim(log, "dst")})
    monkeypatch.setattr(wt, "TRANSFER_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(WorkflowTransferError, match="timed out"):
        await _call()
