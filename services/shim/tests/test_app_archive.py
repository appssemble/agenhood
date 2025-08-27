from __future__ import annotations

import io
import os
import zipfile

import httpx
import pytest

from shim.app import _stream_workspace_zip, create_app

pytestmark = pytest.mark.unit


def app_client(tmp_path):
    app = create_app(workspace=str(tmp_path), token="", drivers={})
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://shim")


def _zip_from(chunks: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(chunks))


def test_stream_workspace_zip_includes_files_excludes_runtime_and_git(tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("bravo")
    (tmp_path / ".agent-runtime").mkdir()
    (tmp_path / ".agent-runtime" / "secret.json").write_text("SECRET")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")

    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    zf = _zip_from(data)
    names = set(zf.namelist())
    assert "a.txt" in names
    assert os.path.join("sub", "b.txt") in names
    assert zf.read("a.txt") == b"alpha"
    assert not any(n.startswith(".agent-runtime") for n in names)
    assert not any(n.startswith(".git") for n in names)


def test_stream_workspace_zip_excludes_gitlink_files(tmp_path):
    # A git submodule / `git worktree add` creates `.git` as a regular FILE
    # (a gitlink) whose body is a `gitdir:` pointer — not a directory. Pruning
    # os.walk's dirnames doesn't catch it, so it must be excluded by name.
    (tmp_path / "submod").mkdir()
    (tmp_path / "submod" / "readme.txt").write_text("hello")
    (tmp_path / "submod" / ".git").write_text("gitdir: /some/path/.git/modules/submod\n")
    # A stray regular file named `.agent-runtime` must also be excluded.
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / ".agent-runtime").write_text("SECRET")

    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    names = set(_zip_from(data).namelist())
    assert os.path.join("submod", "readme.txt") in names
    assert os.path.join("submod", ".git") not in names
    assert not any(os.path.basename(n) == ".git" for n in names)
    assert not any(os.path.basename(n) == ".agent-runtime" for n in names)


def test_stream_workspace_zip_skips_symlinks(tmp_path):
    (tmp_path / "real.txt").write_text("real")
    os.symlink(tmp_path / "real.txt", tmp_path / "link.txt")
    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    names = set(_zip_from(data).namelist())
    assert "real.txt" in names
    assert "link.txt" not in names


def test_stream_workspace_zip_empty_workspace(tmp_path):
    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    assert _zip_from(data).namelist() == []


def test_stream_workspace_zip_large_file_roundtrips(tmp_path):
    # >64 KiB so the chunked read/write path is exercised.
    payload = ("x" * 1000 + "\n") * 300  # ~300 KiB
    (tmp_path / "big.txt").write_text(payload)
    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    assert _zip_from(data).read("big.txt").decode() == payload


def test_zip_excludes_agent_state(tmp_path):
    os.makedirs(tmp_path / ".agent-state" / "codex", exist_ok=True)
    (tmp_path / ".agent-state" / "codex" / "auth.json").write_text("SECRET")
    (tmp_path / "keep.txt").write_text("hi")
    data = b"".join(_stream_workspace_zip(str(tmp_path)))
    assert b"auth.json" not in data
    assert b"SECRET" not in data


@pytest.mark.asyncio
async def test_archive_route_returns_zip(tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    async with app_client(tmp_path) as c:
        resp = await c.get("/files/archive")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        zf = _zip_from(resp.content)
        assert zf.read("a.txt") == b"alpha"


# ---- /files/raw reserved-path guard tests -----------------------------------


@pytest.mark.asyncio
async def test_get_raw_rejects_agent_state_credential(tmp_path):
    cred_dir = tmp_path / ".agent-state" / "codex"
    cred_dir.mkdir(parents=True)
    (cred_dir / "auth.json").write_bytes(b'{"token":"SECRET_CREDENTIAL"}')
    async with app_client(tmp_path) as c:
        resp = await c.get("/files/raw", params={"path": ".agent-state/codex/auth.json"})
    assert resp.status_code == 400
    assert b"SECRET_CREDENTIAL" not in resp.content


@pytest.mark.asyncio
async def test_get_raw_rejects_agent_runtime(tmp_path):
    rt_dir = tmp_path / ".agent-runtime" / "events"
    rt_dir.mkdir(parents=True)
    (rt_dir / "x.jsonl").write_text("runtime-data")
    async with app_client(tmp_path) as c:
        resp = await c.get("/files/raw", params={"path": ".agent-runtime/events/x.jsonl"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_raw_rejects_agent_state(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.put(
            "/files/raw",
            params={"path": ".agent-state/evil.txt"},
            content=b"evil",
        )
    assert resp.status_code == 400
    assert not (tmp_path / ".agent-state" / "evil.txt").exists()


@pytest.mark.asyncio
async def test_raw_get_and_put_normal_file(tmp_path):
    (tmp_path / "hello.txt").write_bytes(b"world")
    async with app_client(tmp_path) as c:
        get_resp = await c.get("/files/raw", params={"path": "hello.txt"})
        assert get_resp.status_code == 200
        assert get_resp.content == b"world"

        put_resp = await c.put(
            "/files/raw",
            params={"path": "new.txt"},
            content=b"fresh",
        )
        assert put_resp.status_code == 204
    assert (tmp_path / "new.txt").read_bytes() == b"fresh"


# ---- DELETE /files/raw -------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_raw_removes_normal_file(tmp_path):
    (tmp_path / "doomed.txt").write_bytes(b"bye")
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": "doomed.txt"})
        assert resp.status_code == 204
    assert not (tmp_path / "doomed.txt").exists()


@pytest.mark.asyncio
async def test_delete_raw_missing_file_404(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": "nope.txt"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_raw_rejects_agent_state(tmp_path):
    cred_dir = tmp_path / ".agent-state" / "codex"
    cred_dir.mkdir(parents=True)
    (cred_dir / "auth.json").write_bytes(b'{"token":"SECRET"}')
    async with app_client(tmp_path) as c:
        resp = await c.delete(
            "/files/raw", params={"path": ".agent-state/codex/auth.json"}
        )
    assert resp.status_code == 400
    assert (cred_dir / "auth.json").exists()


@pytest.mark.asyncio
async def test_delete_raw_rejects_path_escape(tmp_path):
    secret = tmp_path.parent / "outside.txt"
    secret.write_bytes(b"keep me")
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": "../outside.txt"})
    assert resp.status_code == 400
    assert secret.exists()


# ---- directory listing + recursive folder delete ----------------------------


@pytest.mark.asyncio
async def test_list_includes_empty_directories(tmp_path):
    (tmp_path / "emptydir").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("hi")
    async with app_client(tmp_path) as c:
        files = (await c.get("/files")).json()["files"]
    by_path = {f["path"]: f for f in files}
    assert by_path["emptydir"]["is_dir"] is True
    assert by_path["docs"]["is_dir"] is True
    assert by_path["docs/a.txt"]["is_dir"] is False


@pytest.mark.asyncio
async def test_list_does_not_emit_reserved_directories(tmp_path):
    (tmp_path / ".agent-state").mkdir()
    (tmp_path / ".agent-state" / "secret.txt").write_text("s")
    async with app_client(tmp_path) as c:
        files = (await c.get("/files")).json()["files"]
    assert not any(f["path"].startswith(".agent-state") for f in files)


@pytest.mark.asyncio
async def test_delete_raw_removes_directory_recursively(tmp_path):
    d = tmp_path / "sub"
    (d / "nested").mkdir(parents=True)
    (d / "x.txt").write_text("1")
    (d / "nested" / "y.txt").write_text("2")
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": "sub"})
        assert resp.status_code == 204
    assert not d.exists()


@pytest.mark.asyncio
async def test_delete_raw_rejects_reserved_directory(tmp_path):
    rt = tmp_path / ".agent-state"
    rt.mkdir()
    (rt / "secret.txt").write_text("s")
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": ".agent-state"})
    assert resp.status_code == 400
    assert rt.exists()


@pytest.mark.asyncio
async def test_delete_raw_rejects_workspace_root(tmp_path):
    (tmp_path / "keep.txt").write_text("keep")
    async with app_client(tmp_path) as c:
        resp = await c.delete("/files/raw", params={"path": "."})
    assert resp.status_code == 400
    assert (tmp_path / "keep.txt").exists()
