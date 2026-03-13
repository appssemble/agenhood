from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.files as files_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.routers.files import _archive_filename

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
PRINCIPAL = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_1")
_ORIG_SHIM_FOR = files_mod._shim_for
_ORIG_BRING = files_mod.lifecycle.bring_to_running
_ORIG_LIMITS = files_mod.load_tenant_limits

# Records each container id a files request woke (mirrors task-submission wake).
_WOKE: list[str] = []


async def _fake_bring(
    db: Any, dock: Any, shim: Any, cid: str, tenant_id: str, *, limit: int, **kw: Any
) -> None:
    _WOKE.append(cid)


async def _fake_limits(session: Any, tenant_id: str) -> dict:  # type: ignore[type-arg]
    return {"max_running_containers": 5}


class _FakeContainer:
    """Stands in for the SQLAlchemy container Row that _load_owned_container
    returns; _require_running reads .status and the route reads .name."""

    def __init__(self, status: str) -> None:
        self.id = "con_1"
        self.name = "My Box!"
        self.status = status
        self.docker_name = "agent-c-1"
        self.shim_token = "t"
        self.resources = {"_host_shim_url": "http://shim"}


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _FakeSession:
    """Async-context session whose execute().first() returns the container row,
    so the REAL _load_owned_container + _require_running run end-to-end."""

    def __init__(self, row: Any) -> None:
        self._row = row

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, *a: Any, **k: Any) -> _Result:
        return _Result(self._row)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


_DELETED: list[str] = []


class _FakeShim:
    async def __aenter__(self) -> _FakeShim:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def download_archive(self) -> AsyncIterator[bytes]:
        yield b"PK\x03\x04"
        yield b"rest-of-zip"

    async def download_file(self, path: str) -> Any:
        import httpx

        return httpx.Response(
            200, content=b"hello", headers={"content-type": "text/plain"}
        )

    async def delete_file(self, path: str) -> None:
        _DELETED.append(path)

    async def aclose(self) -> None:
        return None


def _setup(status: str) -> None:
    _DELETED.clear()
    _WOKE.clear()
    app.dependency_overrides[resolve_principal] = lambda: PRINCIPAL
    app.state.session_factory = lambda: _FakeSession(_FakeContainer(status))  # type: ignore[assignment]
    files_mod._shim_for = lambda request, row: _FakeShim()  # type: ignore[assignment]
    files_mod.lifecycle.bring_to_running = _fake_bring  # type: ignore[assignment]
    files_mod.load_tenant_limits = _fake_limits  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()
    files_mod._shim_for = _ORIG_SHIM_FOR  # type: ignore[assignment]
    files_mod.lifecycle.bring_to_running = _ORIG_BRING  # type: ignore[assignment]
    files_mod.load_tenant_limits = _ORIG_LIMITS  # type: ignore[assignment]


def test_archive_filename_sanitizes() -> None:
    assert _archive_filename("My Box!") == "My-Box-workspace.zip"
    assert _archive_filename("a/b\\c") == "a-b-c-workspace.zip"
    assert _archive_filename("") == "workspace.zip"


def test_archive_streams_zip_with_attachment_header() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/archive")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="My-Box-workspace.zip"'
    assert r.content == b"PK\x03\x04rest-of-zip"


def test_archive_wakes_paused_container() -> None:
    # Accessing files on a paused container wakes it (like submitting a task)
    # rather than returning 409.
    _setup("paused")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/archive")
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04rest-of-zip"
    assert _WOKE == ["con_1"]


def test_download_file_sets_attachment_filename_from_path() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/raw", params={"path": "src/notes.md"})
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"] == 'attachment; filename="notes.md"'


def test_download_file_encodes_unicode_filename() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/raw", params={"path": "café déjà.txt"})
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment; ")
    # RFC 5987 encoded form preserves the original unicode name.
    assert "filename*=UTF-8''caf%C3%A9%20d%C3%A9j%C3%A0.txt" in cd


def test_delete_file_proxies_to_shim_and_returns_204() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.delete("/v1/containers/con_1/files/raw", params={"path": "a/b.txt"})
    assert r.status_code == 204
    assert _DELETED == ["a/b.txt"]


def test_delete_file_wakes_paused_container() -> None:
    _setup("paused")
    with TestClient(app) as c:
        r = c.delete("/v1/containers/con_1/files/raw", params={"path": "a/b.txt"})
    assert r.status_code == 204
    assert _DELETED == ["a/b.txt"]
    assert _WOKE == ["con_1"]
