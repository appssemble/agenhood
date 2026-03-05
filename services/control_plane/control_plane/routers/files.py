from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import lifecycle
from control_plane.auth import Principal
from control_plane.config import Settings
from control_plane.errors import container_not_runnable
from control_plane.routers.containers import (
    _load_owned_container,
    _principal,
    _session,
    _tid,
    load_tenant_limits,
)
from control_plane.shim_client import ShimClient

router = APIRouter()


def _shim_for(request: Request, row: Any) -> ShimClient:
    settings: Settings = request.app.state.settings
    # If the container was provisioned with host port binding (e.g. on macOS
    # where container IPs are not routable), use the stored host URL directly.
    resources: dict[str, Any] = row.resources or {}
    host_shim_url = resources.get("_host_shim_url")
    base_url = host_shim_url or f"http://{row.docker_name}:{settings.shim_port}"
    return ShimClient(base_url=base_url, token=row.shim_token)


async def _require_running(
    session: AsyncSession, tenant_id: str, cid: str
) -> Any:
    row = await _load_owned_container(session, tenant_id, cid)
    if row.status != "running":
        raise container_not_runnable(f"container is '{row.status}', not running")
    return row


async def _wake_and_load(
    request: Request, session: AsyncSession, tenant_id: str, cid: str
) -> Any:
    """Load an owned container, bringing it to running first.

    Accessing a container's files wakes it the same way submitting a task does
    (spec §4.6): a paused container auto-resumes (an archived one rehydrates)
    under admission control instead of a 409, and an already-running container
    is a no-op. Returns the now-running row (with any refreshed shim URL)."""
    # Ownership / existence guard before any lifecycle action.
    await _load_owned_container(session, tenant_id, cid)
    st = request.app.state
    tenant_limits = await load_tenant_limits(session, tenant_id)
    limit = int(tenant_limits.get("max_running_containers", 5))
    await lifecycle.bring_to_running(
        session,
        getattr(st, "docker_client", None),
        getattr(st, "shim", None),
        cid,
        tenant_id,
        limit=limit,
        settings=st.settings,
    )
    await session.commit()
    return await _load_owned_container(session, tenant_id, cid)


def _archive_filename(name: str) -> str:
    """A safe ``<name>-workspace.zip`` download filename; falls back to plain
    ``workspace.zip`` when the name has no usable characters."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return f"{base}-workspace.zip" if base else "workspace.zip"


def _attachment_disposition(path: str) -> str:
    """Build a ``Content-Disposition`` value that downloads a container file
    under its original basename and extension (e.g. ``src/notes.md`` →
    ``notes.md``) instead of the route's ``raw`` segment.

    Emits both a sanitized ASCII ``filename`` fallback and an RFC 5987
    ``filename*`` so non-ASCII names round-trip in modern browsers."""
    name = re.split(r"[\\/]", path)[-1] or "download"
    ascii_name = (
        name.encode("ascii", "ignore").decode("ascii").replace('"', "").replace("\\", "")
        or "download"
    )
    if ascii_name == name:
        return f'attachment; filename="{ascii_name}"'
    quoted = quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


@router.get("/containers/{cid}/files")
async def list_files(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
    prefix: str | None = None,
) -> dict:  # type: ignore[type-arg]
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        return await shim.list_files(prefix)


@router.get("/containers/{cid}/files/raw", response_model=None)
async def download_file(
    cid: str,
    path: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        resp = await shim.download_file(path)
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Content-Disposition": _attachment_disposition(path)},
    )


@router.put("/containers/{cid}/files/raw", status_code=204, response_model=None)
async def upload_file(
    cid: str,
    path: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    row = await _wake_and_load(request, session, _tid(principal), cid)
    content = await request.body()
    async with _shim_for(request, row) as shim:
        await shim.upload_file(path, content)
    return Response(status_code=204)


@router.delete("/containers/{cid}/files/raw", status_code=204, response_model=None)
async def delete_file(
    cid: str,
    path: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        await shim.delete_file(path)
    return Response(status_code=204)


@router.get("/containers/{cid}/files/archive", response_model=None)
async def download_archive(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> StreamingResponse:
    row = await _wake_and_load(request, session, _tid(principal), cid)
    filename = _archive_filename(row.name or cid)
    shim = _shim_for(request, row)

    async def gen() -> Any:
        try:
            async for chunk in shim.download_archive():
                yield chunk
        finally:
            await shim.aclose()

    return StreamingResponse(
        gen(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
