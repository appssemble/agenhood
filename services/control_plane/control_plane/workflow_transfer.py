"""Cross-container file transfer between workflow steps.

Moves a completed step's declared ``exports`` into the next step's container
before its task is submitted (workflow file transfer spec). Called from the
engine's submit phase — never under a row lock. Every failure surfaces as
WorkflowTransferError; its message becomes the run's error_message.
"""
from __future__ import annotations

import asyncio
from typing import Any

from control_plane import lifecycle
from control_plane.routers.containers import _load_owned_container, load_tenant_limits
from control_plane.routers.tasks import _shim_for
from control_plane.shim_client import (
    ShimError,
    ShimExportUnmatched,
    ShimTransferTooLarge,
)

TRANSFER_TIMEOUT_SECONDS = 600


class WorkflowTransferError(Exception):
    """A step's export transfer failed; the message is the run error."""


async def _wake(
    session: Any, *, settings: Any, docker_client: Any, shim_dispatcher: Any,
    tenant_id: str, cid: str,
) -> Any:
    """Bring a container to running (same wake path as file routes / task
    submit) and return its fresh row."""
    await _load_owned_container(session, tenant_id, cid)
    tenant_limits = await load_tenant_limits(session, tenant_id)
    limit = int(tenant_limits.get("max_running_containers", 5))
    await lifecycle.bring_to_running(
        session, docker_client, shim_dispatcher, cid, tenant_id,
        limit=limit, settings=settings,
    )
    await session.commit()
    return await _load_owned_container(session, tenant_id, cid)


async def transfer_step_exports(
    session: Any,
    *,
    settings: Any,
    docker_client: Any,
    shim_dispatcher: Any,
    tenant_id: str,
    exports: list[str],
    source_cid: str,
    dest_cid: str,
) -> dict[str, int]:
    """Validate and copy ``exports`` from source to destination workspace.

    Same-container handoffs only dry-run (missing-export contract still
    enforced; the files are already in place). Returns ``{"files","bytes"}``
    for the run timeline / files_transferred event.
    """
    cap = int(getattr(settings, "workflow_transfer_max_bytes", 0)) or None
    try:
        async with asyncio.timeout(TRANSFER_TIMEOUT_SECONDS):
            src_row = await _wake(
                session, settings=settings, docker_client=docker_client,
                shim_dispatcher=shim_dispatcher, tenant_id=tenant_id, cid=source_cid,
            )
            src = _shim_for(settings, src_row)
            try:
                manifest = await src.export_manifest(exports, max_bytes=cap)
                if source_cid == dest_cid:
                    return {
                        "files": len(manifest["files"]),
                        "bytes": int(manifest["total_bytes"]),
                    }
                dest_row = await _wake(
                    session, settings=settings, docker_client=docker_client,
                    shim_dispatcher=shim_dispatcher, tenant_id=tenant_id, cid=dest_cid,
                )
                dest = _shim_for(settings, dest_row)
                try:
                    result = await dest.import_archive(
                        src.export_stream(exports, max_bytes=cap), max_bytes=cap
                    )
                finally:
                    await dest.aclose()
                return {
                    "files": int(result["files_written"]),
                    "bytes": int(result["bytes_written"]),
                }
            finally:
                await src.aclose()
    except WorkflowTransferError:
        raise
    except ShimExportUnmatched as exc:
        raise WorkflowTransferError(str(exc)) from exc
    except ShimTransferTooLarge as exc:
        raise WorkflowTransferError(
            f"export exceeds the transfer size cap ({cap} bytes)"
        ) from exc
    except TimeoutError as exc:
        raise WorkflowTransferError(
            f"file transfer timed out after {TRANSFER_TIMEOUT_SECONDS}s"
        ) from exc
    except ShimError as exc:
        raise WorkflowTransferError(f"file transfer failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — a transfer bug must fail the
        # run, not crash the scheduler sweep for every other tenant.
        raise WorkflowTransferError(f"file transfer failed: {exc}") from exc
