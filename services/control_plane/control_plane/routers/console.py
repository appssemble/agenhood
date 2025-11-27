"""Container console: a WebSocket-backed interactive root shell (docker exec).

This is the service's first WebSocket route. Auth mirrors the HTTP routers
(session cookie / API key -> tenant-scoped Principal), but resolution reads from
the WebSocket handshake rather than an HTTP Request.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import anyio
from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect, WebSocketState

from control_plane.audit import audit
from control_plane.auth.principal import (
    DbPrincipalRepo,
    Principal,
    resolve_from_inputs,
)
from control_plane.console_exec import make_console_exec
from control_plane.models_db import containers

log = logging.getLogger("control_plane.console")
router = APIRouter()

# Idle timeout: close a session after this long with no client input (resource
# hygiene; not a usage limit).
_IDLE_TIMEOUT_SECONDS = 15 * 60

# Close codes (see plan "Message Protocol").
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_FORBIDDEN = 4403
_CLOSE_NOT_FOUND = 4404
_CLOSE_NOT_RUNNING = 4409
_CLOSE_INTERNAL = 1011


async def _principal_ws(websocket: WebSocket) -> Principal | None:
    """Resolve a tenant-scoped Principal from the WebSocket handshake.

    Returns None when auth fails or the credential is staff-only (staff have
    tenant_id=None and cannot touch tenant resources). Overridable in tests via
    app.dependency_overrides.
    """
    factory = websocket.app.state.session_factory
    settings = websocket.app.state.settings
    cookie_token = websocket.cookies.get("agent_session")
    authorization = websocket.headers.get("authorization")
    admin_api_key_env = getattr(settings, "admin_api_key", None)
    async with factory() as conn:
        repo = DbPrincipalRepo(conn)
        p = await resolve_from_inputs(
            repo,
            authorization=authorization,
            cookie_token=cookie_token,
            admin_api_key_env=admin_api_key_env,
        )
    if p is None or p.tenant_id is None:
        return None
    return p


def _origin_ok(websocket: WebSocket) -> bool:
    """Same-origin guard against cross-site WebSocket hijacking.

    Browsers always send Origin; reject when its hostname differs from the
    request Host. Hostnames are compared *ignoring port*: a cross-site attacker
    is on a different hostname (rejected), while a legitimate client may differ
    by port — e.g. local dev connects the console WS straight to the
    control-plane's published port because the vite proxy does not forward WS
    upgrades. Absent Origin (non-browser clients / tests) is allowed.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    host = websocket.headers.get("host")
    if not host:
        return False
    origin_host = origin.split("://", 1)[-1].split(":", 1)[0]
    host_host = host.split(":", 1)[0]
    return origin_host == host_host


async def _load_owned_running(websocket: WebSocket, principal: Principal, cid: str) -> Any:
    """Return the container row if owned + running, else send the right close
    code and return None."""
    factory = websocket.app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(
                select(containers).where(
                    containers.c.id == cid,
                    containers.c.tenant_id == principal.tenant_id,
                )
            )
        ).first()
    if row is None:
        await websocket.close(code=_CLOSE_NOT_FOUND, reason="container not found")
        return None
    if row.status != "running":
        await websocket.close(
            code=_CLOSE_NOT_RUNNING, reason=f"container is '{row.status}', not running"
        )
        return None
    return row


async def _pump_exec_to_ws(exec_session: Any, websocket: WebSocket) -> None:
    while True:
        data = await exec_session.recv(4096)
        if data == b"":  # shell exited
            return
        await websocket.send_bytes(data)


async def _pump_ws_to_exec(exec_session: Any, websocket: WebSocket) -> None:
    while True:
        msg = await asyncio.wait_for(websocket.receive(), timeout=_IDLE_TIMEOUT_SECONDS)
        if msg["type"] == "websocket.disconnect":
            return
        if (data := msg.get("bytes")) is not None:
            await exec_session.send(data)
        elif (text := msg.get("text")) is not None:
            try:
                ctrl = json.loads(text)
            except ValueError:
                continue
            if ctrl.get("type") == "resize":
                await exec_session.resize(
                    rows=int(ctrl.get("rows", 24)), cols=int(ctrl.get("cols", 80))
                )


async def _audit(websocket: WebSocket, **kw: Any) -> None:
    factory = websocket.app.state.session_factory
    async with factory() as s:
        await audit(s, **kw)
        await s.commit()


@router.websocket("/containers/{cid}/console")
async def console(
    websocket: WebSocket,
    cid: str,
    principal: Principal | None = Depends(_principal_ws),
) -> None:
    if not _origin_ok(websocket):
        await websocket.close(code=_CLOSE_FORBIDDEN, reason="bad origin")
        return

    await websocket.accept()

    if principal is None:
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="authentication required")
        return

    row = await _load_owned_running(websocket, principal, cid)
    if row is None:
        return

    docker_client = getattr(websocket.app.state, "docker_client", None)
    if docker_client is None:
        await websocket.close(code=_CLOSE_INTERNAL, reason="docker unavailable")
        return

    client_ip = websocket.client.host if websocket.client else None
    try:
        exec_session = make_console_exec(
            docker_client=docker_client, docker_name=row.docker_name, user="root"
        )
    except Exception:  # noqa: BLE001
        log.exception("console exec failed to start for %s", cid)
        await websocket.close(code=_CLOSE_INTERNAL, reason="could not start shell")
        return

    await _audit(
        websocket,
        actor_type="tenant",
        actor_id=principal.user_id,
        action="console.session.open",
        target_type="container",
        target_id=cid,
        details={"client_ip": client_ip, "exec_user": "root"},
    )

    # Run both pumps under an anyio task group (Starlette runs on anyio). The
    # first pump to finish cancels the scope, tearing the other down cleanly —
    # no leaked CancelledError, unlike hand-rolled asyncio.create_task/wait.
    end_reason = "user_disconnect"

    async def _run_out(scope: anyio.CancelScope) -> None:
        try:
            await _pump_exec_to_ws(exec_session, websocket)
        finally:
            scope.cancel()  # shell exited / output stream ended

    async def _run_in(scope: anyio.CancelScope) -> None:
        nonlocal end_reason
        try:
            await _pump_ws_to_exec(exec_session, websocket)
        except TimeoutError:
            end_reason = "idle_timeout"
        finally:
            scope.cancel()  # client disconnected / idle timeout

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_run_out, tg.cancel_scope)
            tg.start_soon(_run_in, tg.cancel_scope)
    except WebSocketDisconnect:
        end_reason = "user_disconnect"
    except Exception:  # noqa: BLE001
        end_reason = "error"
        log.exception("console session error for %s", cid)
    finally:
        exec_session.close()
        # Shield teardown (audit + close) from any external cancellation so the
        # close-session audit row is always written.
        with anyio.CancelScope(shield=True):
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
            await _audit(
                websocket,
                actor_type="tenant",
                actor_id=principal.user_id,
                action="console.session.close",
                target_type="container",
                target_id=cid,
                details={"end_reason": end_reason},
            )
