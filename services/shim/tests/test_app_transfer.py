"""/files/export and /files/import endpoint tests (workflow file transfer)."""
from __future__ import annotations

import io
import os
import tarfile

import httpx
import pytest

from shim.app import create_app

pytestmark = pytest.mark.unit


def app_client(ws):
    app = create_app(workspace=str(ws), token="", drivers={})
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://shim")


def _mk(ws, rel, content=b"x"):
    full = os.path.join(str(ws), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(content)


@pytest.mark.asyncio
async def test_export_dry_run_manifest(tmp_path):
    _mk(tmp_path, "report.pdf", b"12345")
    _mk(tmp_path, "dist/a.js", b"aa")
    async with app_client(tmp_path) as c:
        r = await c.get("/files/export", params=[
            ("paths", "report.pdf"), ("paths", "dist/**"), ("dry_run", "true"),
        ])
        assert r.status_code == 200
        body = r.json()
        assert body["total_bytes"] == 7
        assert [f["path"] for f in body["files"]] == ["dist/a.js", "report.pdf"]


@pytest.mark.asyncio
async def test_export_unmatched_pattern_422(tmp_path):
    _mk(tmp_path, "a.txt")
    async with app_client(tmp_path) as c:
        r = await c.get("/files/export", params=[
            ("paths", "a.txt"), ("paths", "missing/**"),
        ])
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "unmatched_exports"
        assert r.json()["error"]["unmatched"] == ["missing/**"]


@pytest.mark.asyncio
async def test_export_over_cap_413(tmp_path):
    _mk(tmp_path, "big.bin", b"z" * 100)
    async with app_client(tmp_path) as c:
        r = await c.get("/files/export", params=[("paths", "big.bin"), ("max_bytes", "10")])
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "transfer_too_large"
        assert r.json()["error"]["total_bytes"] == 100


@pytest.mark.asyncio
async def test_export_requires_paths(tmp_path):
    async with app_client(tmp_path) as c:
        r = await c.get("/files/export")
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_export_streams_tar(tmp_path):
    _mk(tmp_path, "dist/a.js", b"aa")
    async with app_client(tmp_path) as c:
        r = await c.get("/files/export", params=[("paths", "dist/**")])
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-tar")
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r") as tf:
            assert tf.extractfile("dist/a.js").read() == b"aa"


@pytest.mark.asyncio
async def test_import_round_trip(tmp_path):
    src_ws = tmp_path / "src"
    dst_ws = tmp_path / "dst"
    os.makedirs(src_ws); os.makedirs(dst_ws)
    _mk(src_ws, "out/result.txt", b"payload")
    async with app_client(src_ws) as src, app_client(dst_ws) as dst:
        exported = await src.get("/files/export", params=[("paths", "out/**")])
        r = await dst.post("/files/import", content=exported.content)
        assert r.status_code == 200
        assert r.json() == {"files_written": 1, "bytes_written": 7}
    assert open(dst_ws / "out/result.txt", "rb").read() == b"payload"


@pytest.mark.asyncio
async def test_import_rejects_traversal_400(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"evil"))
    async with app_client(tmp_path) as c:
        r = await c.post("/files/import", content=buf.getvalue())
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invalid_archive"
    assert not os.path.exists(tmp_path.parent / "evil.txt")


@pytest.mark.asyncio
async def test_import_garbage_body_400(tmp_path):
    async with app_client(tmp_path) as c:
        r = await c.post("/files/import", content=b"this is not a tar")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_import_over_cap_413(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("big.bin")
        info.size = 100
        tf.addfile(info, io.BytesIO(b"z" * 100))
    async with app_client(tmp_path) as c:
        r = await c.post("/files/import", params={"max_bytes": "10"},
                         content=buf.getvalue())
        assert r.status_code == 413
    # spool file cleaned up
    spool_dir = os.path.join(str(tmp_path), ".agent-runtime", "tmp")
    assert not os.path.isdir(spool_dir) or os.listdir(spool_dir) == []
