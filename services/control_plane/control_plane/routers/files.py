from __future__ import annotations

import re
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import lifecycle
from control_plane.auth import Principal
from control_plane.config import Settings
from control_plane.errors import api_error, container_not_runnable
from control_plane.routers.containers import (
    _load_owned_container,
    _principal,
    _session,
    _tid,
    load_tenant_limits,
)
from control_plane.shim_client import (
    ShimClient,
    ShimExportUnmatched,
    ShimTransferTooLarge,
)

router = APIRouter(tags=["Files"])


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


@router.get(
    "/containers/{cid}/files",
    response_description="Listing of workspace files (as returned by the container shim).",
)
async def list_files(
    cid: Annotated[str, Path(description="Container id.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
    prefix: Annotated[
        str | None,
        Query(description="Optional workspace-relative path prefix to filter the listing."),
    ] = None,
) -> dict:  # type: ignore[type-arg]
    """List files in a container's workspace.

    Requires a tenant-scoped bearer credential owning the container (staff
    credentials with tenant_id=None are rejected with 403). Accessing a
    container's files wakes it: a paused container auto-resumes and an archived
    one rehydrates under admission control (spec §4.6), so this call has the
    side effect of bringing the container to running.

    Errors: 403 when the credential is not tenant-scoped; 404 when the
    container does not exist or belongs to another tenant; 409 if the container
    cannot be brought to running.
    """
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        return await shim.list_files(prefix)


@router.get(
    "/containers/{cid}/files/raw",
    response_model=None,
    response_description=(
        "Raw file bytes streamed as an attachment download; media type mirrors the "
        "file's own content type, defaulting to application/octet-stream."
    ),
)
async def download_file(
    cid: Annotated[str, Path(description="Container id.")],
    path: Annotated[str, Query(description="Workspace-relative path of the file to download.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    """Download the raw contents of a single workspace file.

    Returns the file bytes with a Content-Disposition attachment header naming
    the file by its original basename. The response media type is taken from
    the container shim's content-type header, defaulting to
    application/octet-stream.

    Requires a tenant-scoped bearer credential owning the container (staff
    credentials are rejected with 403). Wakes the container as a side effect
    (spec §4.6): a paused container auto-resumes and an archived one rehydrates.

    Errors: 403 when the credential is not tenant-scoped; 404 when the
    container does not exist or belongs to another tenant; 409 if the container
    cannot be brought to running.
    """
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        resp = await shim.download_file(path)
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Content-Disposition": _attachment_disposition(path)},
    )


@router.put(
    "/containers/{cid}/files/raw",
    status_code=204,
    response_model=None,
    response_description="No content; the file was written to the workspace.",
)
async def upload_file(
    cid: Annotated[str, Path(description="Container id.")],
    path: Annotated[
        str, Query(description="Workspace-relative path to write the uploaded bytes to.")
    ],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    """Upload (create or overwrite) a single workspace file.

    The raw request body (any media type, e.g. application/octet-stream) is
    written verbatim to the given workspace path in the container. Returns 204
    No Content on success.

    Requires a tenant-scoped bearer credential owning the container (staff
    credentials are rejected with 403). Wakes the container as a side effect
    (spec §4.6): a paused container auto-resumes and an archived one rehydrates.

    Errors: 403 when the credential is not tenant-scoped; 404 when the
    container does not exist or belongs to another tenant; 409 if the container
    cannot be brought to running.
    """
    row = await _wake_and_load(request, session, _tid(principal), cid)
    content = await request.body()
    async with _shim_for(request, row) as shim:
        await shim.upload_file(path, content)
    return Response(status_code=204)


@router.delete(
    "/containers/{cid}/files/raw",
    status_code=204,
    response_model=None,
    response_description="No content; the file was removed from the workspace.",
)
async def delete_file(
    cid: Annotated[str, Path(description="Container id.")],
    path: Annotated[str, Query(description="Workspace-relative path of the file to delete.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    """Delete a single workspace file.

    Removes the file at the given workspace path in the container. Returns 204
    No Content on success.

    Requires a tenant-scoped bearer credential owning the container (staff
    credentials are rejected with 403). Wakes the container as a side effect
    (spec §4.6): a paused container auto-resumes and an archived one rehydrates.

    Errors: 403 when the credential is not tenant-scoped; 404 when the
    container does not exist or belongs to another tenant; 409 if the container
    cannot be brought to running.
    """
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        await shim.delete_file(path)
    return Response(status_code=204)


@router.get(
    "/containers/{cid}/files/archive",
    response_model=None,
    response_description=(
        "The workspace streamed as a zip archive (media type application/zip) "
        "delivered as a `<name>-workspace.zip` attachment download."
    ),
)
async def download_archive(
    cid: Annotated[str, Path(description="Container id.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> StreamingResponse:
    """Download the entire workspace as a zip archive.

    Streams the container's workspace as an application/zip archive delivered
    with a Content-Disposition attachment header (filename derived from the
    container name, e.g. `<name>-workspace.zip`). The archive is streamed
    chunk-by-chunk from the container shim.

    Requires a tenant-scoped bearer credential owning the container (staff
    credentials are rejected with 403). Wakes the container as a side effect
    (spec §4.6): a paused container auto-resumes and an archived one rehydrates.

    Errors: 403 when the credential is not tenant-scoped; 404 when the
    container does not exist or belongs to another tenant; 409 if the container
    cannot be brought to running.
    """
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


@router.get(
    "/containers/{cid}/files/export",
    response_model=None,
    response_description=(
        "With dry_run=true, a JSON manifest {files:[{path,size}], total_bytes}; "
        "otherwise the matched files streamed as an uncompressed tar."
    ),
)
async def export_files(
    cid: Annotated[str, Path(description="Container id.")],
    request: Request,
    paths: Annotated[
        list[str], Query(description="Workspace-relative paths or glob patterns to export.")
    ],
    dry_run: Annotated[
        bool, Query(description="Return the manifest instead of the tar body.")
    ] = False,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response | StreamingResponse | dict:  # type: ignore[type-arg]
    """Export workspace files matched by paths/globs as a tar (or manifest).

    Same wake semantics as the other file routes (spec §4.6). A pattern that
    matches no regular file yields 422 unmatched_exports; a match set larger
    than WORKFLOW_TRANSFER_MAX_BYTES yields 413 transfer_too_large.
    """
    settings: Settings = request.app.state.settings
    cap = settings.workflow_transfer_max_bytes
    row = await _wake_and_load(request, session, _tid(principal), cid)
    shim = _shim_for(request, row)
    try:
        # Manifest first even when streaming: validates patterns + cap before
        # any body bytes are committed to the response.
        manifest = await shim.export_manifest(paths, max_bytes=cap)
    except ShimExportUnmatched as e:
        await shim.aclose()
        raise api_error(422, "unmatched_exports", str(e), "paths") from e
    except ShimTransferTooLarge as e:
        await shim.aclose()
        raise api_error(413, "transfer_too_large", str(e), "paths") from e
    except Exception:
        await shim.aclose()
        raise
    if dry_run:
        await shim.aclose()
        return manifest

    async def gen() -> Any:
        try:
            async for chunk in shim.export_stream(paths, max_bytes=cap):
                yield chunk
        finally:
            await shim.aclose()

    return StreamingResponse(
        gen(),
        media_type="application/x-tar",
        headers={"Content-Disposition": 'attachment; filename="export.tar"'},
    )


@router.post(
    "/containers/{cid}/files/import",
    response_model=None,
    response_description="Counts of files/bytes written to the workspace.",
)
async def import_files(
    cid: Annotated[str, Path(description="Container id.")],
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Import an uncompressed tar (request body) into the workspace.

    Regular files/directories only; absolute, traversing, reserved or
    symlink members are rejected with 400 invalid_archive. Bodies over
    WORKFLOW_TRANSFER_MAX_BYTES are rejected with 413.
    """
    settings: Settings = request.app.state.settings
    cap = settings.workflow_transfer_max_bytes
    row = await _wake_and_load(request, session, _tid(principal), cid)
    async with _shim_for(request, row) as shim:
        try:
            return await shim.import_archive(request.stream(), max_bytes=cap)
        except ShimTransferTooLarge as e:
            raise api_error(413, "transfer_too_large", str(e), "body") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise api_error(
                    400, "invalid_archive", e.response.text, "body"
                ) from e
            raise
