from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import control_plane.routers.files as files_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.shim_client import ShimExportUnmatched, ShimTransferTooLarge

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

# Recorded kwargs from the fake shim's export/import calls, for assertions.
_CALLS: dict[str, Any] = {}


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


_MANIFEST = {"files": [{"path": "a.txt", "size": 3}], "total_bytes": 3}
_EXPORT_ERROR: Exception | None = None
_IMPORT_ERROR: Exception | None = None
_IMPORT_RESULT = {"files_written": 1, "bytes_written": 3}


class _FakeShim:
    async def __aenter__(self) -> _FakeShim:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def export_manifest(
        self, paths: list[str], *, max_bytes: int | None = None
    ) -> dict[str, Any]:
        _CALLS["export_manifest"] = {"paths": paths, "max_bytes": max_bytes}
        if _EXPORT_ERROR is not None:
            raise _EXPORT_ERROR
        return _MANIFEST

    async def export_stream(
        self, paths: list[str], *, max_bytes: int | None = None
    ) -> AsyncIterator[bytes]:
        _CALLS["export_stream"] = {"paths": paths, "max_bytes": max_bytes}
        yield b"tar-chunk-1"
        yield b"tar-chunk-2"

    async def import_archive(
        self, content: AsyncIterator[bytes], *, max_bytes: int | None = None
    ) -> dict[str, Any]:
        body = b""
        async for chunk in content:
            body += chunk
        _CALLS["import_archive"] = {"body": body, "max_bytes": max_bytes}
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        return _IMPORT_RESULT

    async def aclose(self) -> None:
        return None


def _setup(status: str) -> None:
    global _EXPORT_ERROR, _IMPORT_ERROR
    _WOKE.clear()
    _CALLS.clear()
    _EXPORT_ERROR = None
    _IMPORT_ERROR = None
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


def test_export_dry_run_returns_manifest_with_settings_cap() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.get(
            "/v1/containers/con_1/files/export",
            params={"paths": "a.txt", "dry_run": "true"},
        )
    assert r.status_code == 200
    assert r.json() == _MANIFEST
    assert _CALLS["export_manifest"]["max_bytes"] == _SETTINGS.workflow_transfer_max_bytes


def test_export_without_dry_run_streams_tar() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/export", params={"paths": "a.txt"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-tar"
    assert r.content == b"tar-chunk-1tar-chunk-2"


def test_export_unmatched_returns_422() -> None:
    global _EXPORT_ERROR
    _setup("running")
    _EXPORT_ERROR = ShimExportUnmatched(["x"])
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/export", params={"paths": "x"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unmatched_exports"


def test_export_too_large_returns_413() -> None:
    global _EXPORT_ERROR
    _setup("running")
    _EXPORT_ERROR = ShimTransferTooLarge("too big")
    with TestClient(app) as c:
        r = c.get("/v1/containers/con_1/files/export", params={"paths": "a.txt"})
    assert r.status_code == 413


def test_import_returns_counts_and_forwards_body() -> None:
    _setup("running")
    with TestClient(app) as c:
        r = c.post("/v1/containers/con_1/files/import", content=b"abc")
    assert r.status_code == 200
    assert r.json() == _IMPORT_RESULT
    assert _CALLS["import_archive"]["body"] == b"abc"


def test_import_invalid_archive_returns_400() -> None:
    global _IMPORT_ERROR
    _setup("running")
    request = httpx.Request("POST", "http://shim/files/import")
    response = httpx.Response(400, text="bad archive", request=request)
    _IMPORT_ERROR = httpx.HTTPStatusError("bad", request=request, response=response)
    with TestClient(app) as c:
        r = c.post("/v1/containers/con_1/files/import", content=b"abc")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_archive"
