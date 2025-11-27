from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import control_plane.routers.console as console_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal
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
PRINCIPAL = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id="usr_1")


class _FakeContainer:
    def __init__(self, status: str) -> None:
        self.id = "con_1"
        self.name = "box"
        self.status = status
        self.docker_name = "agent-c-1"
        self.tenant_id = "ten_1"


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _FakeSession:
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


class _FakeExec:
    """Scripts output chunks, records stdin + resize, blocks like a live shell."""

    def __init__(self) -> None:
        self._out = [b"hello\r\n"]
        self.stdin: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.closed = False

    async def recv(self, n: int = 4096) -> bytes:
        if self._out:
            return self._out.pop(0)
        await asyncio.Event().wait()  # live shell: no more output until cancelled
        return b""

    async def send(self, data: bytes) -> None:
        self.stdin.append(data)

    async def resize(self, *, rows: int, cols: int) -> None:
        self.resizes.append((rows, cols))

    def close(self) -> None:
        self.closed = True


def _setup(status: str = "running", principal: Principal | None = PRINCIPAL) -> _FakeExec:
    fake = _FakeExec()
    app.dependency_overrides[console_mod._principal_ws] = lambda: principal
    app.state.session_factory = lambda: _FakeSession(_FakeContainer(status))  # type: ignore[assignment]
    app.state.docker_client = object()
    console_mod.make_console_exec = lambda **kw: fake  # type: ignore[assignment]
    return fake


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_streams_output_and_accepts_input_then_closes():
    fake = _setup("running")
    client = TestClient(app)
    with client.websocket_connect("/v1/containers/con_1/console") as ws:
        assert ws.receive_bytes() == b"hello\r\n"
        ws.send_bytes(b"ls\n")
        ws.send_json({"type": "resize", "cols": 100, "rows": 30})
    assert fake.stdin == [b"ls\n"]
    assert fake.resizes == [(30, 100)]
    assert fake.closed is True


def test_rejects_unauthenticated():
    _setup("running", principal=None)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/v1/containers/con_1/console") as ws:
            ws.receive_bytes()
    assert ei.value.code == 4401


def test_rejects_when_not_running():
    _setup("paused")
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/v1/containers/con_1/console") as ws:
            ws.receive_bytes()
    assert ei.value.code == 4409


def test_rejects_not_found_or_cross_tenant():
    _setup("running")
    app.state.session_factory = lambda: _FakeSession(None)  # type: ignore[assignment]
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/v1/containers/con_1/console") as ws:
            ws.receive_bytes()
    assert ei.value.code == 4404


# ---------------------------------------------------------------------------
# _origin_ok: hostname-based same-origin guard (ignores port so dev can connect
# the console WS directly to the control-plane's published port).
# ---------------------------------------------------------------------------


class _Hdr:
    def __init__(self, headers: dict[str, str]) -> None:
        self._h = headers

    def get(self, k: str, default: Any = None) -> Any:
        return self._h.get(k, default)


class _WS:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = _Hdr(headers)


def test_origin_ok_allows_absent_origin():
    assert console_mod._origin_ok(_WS({"host": "localhost:8443"})) is True


def test_origin_ok_allows_same_host_different_port():
    # Browser page on :5173, console WS to the control-plane on :8443 (dev).
    ws = _WS({"origin": "http://localhost:5173", "host": "localhost:8443"})
    assert console_mod._origin_ok(ws) is True


def test_origin_ok_allows_same_origin_prod():
    ws = _WS({"origin": "https://app.example.com", "host": "app.example.com"})
    assert console_mod._origin_ok(ws) is True


def test_origin_ok_rejects_cross_site():
    ws = _WS({"origin": "https://evil.example", "host": "app.example.com"})
    assert console_mod._origin_ok(ws) is False
