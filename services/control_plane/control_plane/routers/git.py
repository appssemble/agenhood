"""Per-container git endpoints (workspace git rollback spec).

Shim-touching routes require a running container (same rule as the file
routes); the remote CRUD reads/writes only the DB except for the link-time
verify, which needs the shim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.auth import Principal
from control_plane.auth.crypto import load_key_from_env
from control_plane.errors import api_error, not_found
from control_plane.git_remotes_service import (
    DeployKey,
    build_remote_row,
    decrypt_private_key,
    generate_deploy_key,
    public_remote_view,
    validate_branch,
    validate_remote_url,
)
from control_plane.linked_repos_service import build_linked_row, public_linked_view
from control_plane.models_db import containers, git_remotes, linked_repos
from control_plane.routers.containers import (
    _load_owned_container,
    _principal,
    _session,
    _tid,
)
from control_plane.routers.files import _require_running, _shim_for
from control_plane.shim_client import ShimGitConflict, ShimGitNotFound

router = APIRouter()


class RemoteIn(BaseModel):
    url: str
    branch: str = "main"
    enabled: bool = True


class VerifyIn(BaseModel):
    url: str


class LinkIn(BaseModel):
    url: str
    branch: str = "main"
    confirm: bool = False


class RepullIn(BaseModel):
    confirm: bool = False


async def _shim_verify(shim: Any, *, url: str, key: str) -> dict[str, Any]:
    """Call the shim's git_verify, mapping transport/HTTP errors (shim down,
    starting up, or an older image without the route) to a friendly 502 instead
    of leaking an unhandled 500."""
    try:
        return await shim.git_verify(url=url, ssh_private_key=key)
    except httpx.HTTPError as exc:
        raise api_error(
            502, "shim_unreachable",
            "could not reach the agent (it may be starting up or running an "
            "older image); try again in a moment",
        ) from exc


async def _shim_push(shim: Any, *, url: str, key: str, branch: str) -> dict[str, Any]:
    """Call the shim's git_push, mapping transport/HTTP errors to a friendly 502."""
    try:
        return await shim.git_push(url=url, ssh_private_key=key, branch=branch)
    except httpx.HTTPError as exc:
        raise api_error(
            502, "shim_unreachable",
            "could not reach the agent to push; try again in a moment",
        ) from exc


class RollbackIn(BaseModel):
    sha: str


# ---- pure helpers (unit-tested) ---------------------------------------------

def _verify_message(code: str | None) -> str:
    return {
        "auth_failed": "authentication failed. Is the deploy key added with write access?",
        "host_unreachable": "host unreachable; check the URL",
        "repo_not_found": "repository not found",
        "egress_blocked": "blocked by network policy",
        "host_key_changed": "remote host key changed; verify the host",
    }.get(code or "", "could not reach the remote")


def push_record_values(result: dict[str, Any]) -> dict[str, Any]:
    """git_remotes column updates for one push attempt."""
    ok = bool(result.get("ok"))
    now = datetime.now(UTC)
    return {
        "last_push_status": "pushed" if ok else "failed",
        "last_push_error": None if ok else result.get("error_code", "push_failed"),
        "last_push_at": now,
        "updated_at": now,
    }


# ---- DB access ----------------------------------------------------------------

async def _load_remote(session: AsyncSession, cid: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(git_remotes).where(git_remotes.c.container_id == cid)
        )
    ).mappings().first()
    return dict(row) if row else None


async def _record_push(session: AsyncSession, cid: str, result: dict[str, Any]) -> None:
    await session.execute(
        git_remotes.update()
        .where(git_remotes.c.container_id == cid)
        .values(**push_record_values(result))
    )
    await session.commit()


async def _load_linked(session: AsyncSession, cid: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(linked_repos).where(linked_repos.c.container_id == cid)
        )
    ).mappings().first()
    return dict(row) if row else None


async def _set_git_mode(session: AsyncSession, cid: str, mode: str) -> None:
    await session.execute(
        containers.update().where(containers.c.id == cid).values(git_mode=mode)
    )


async def _no_task_running(session: AsyncSession, cid: str) -> None:
    """Guard: clone/repull/link must not race a running task."""
    from control_plane.models_db import tasks  # local import: avoid cycle

    running = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(tasks)
            .where(tasks.c.container_id == cid, tasks.c.status == "running")
        )
    ).scalar_one()
    if running:
        raise api_error(409, "task_running", "cannot link while a task is running")


# ---- routes -------------------------------------------------------------------

@router.get("/containers/{cid}/git/snapshots")
async def list_snapshots(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = await _require_running(session, _tid(principal), cid)
    if row.git_mode == "linked":
        # Pull mode: there are no local snapshots to roll back to. Return a
        # disabled marker (and the linked repo coordinates) WITHOUT touching
        # the shim, so the UI can show the linked state instead of a history.
        linked = await _load_linked(session, cid)
        return {
            "snapshots": [],
            "disabled": True,
            "linked": (
                {"url": linked["url"], "branch": linked["branch"]}
                if linked
                else None
            ),
        }
    async with _shim_for(request, row) as shim:
        try:
            return await shim.git_log()
        except httpx.HTTPError:
            # Shim unreachable or running an older image without /git/log:
            # degrade to no snapshots so the page renders instead of 500ing
            # (and the spinner never resolving).
            return {"snapshots": []}


@router.get("/containers/{cid}/git/remote")
async def get_remote(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    # DB-only: works in any container state (the delete dialog reads this).
    await _load_owned_container(session, _tid(principal), cid)
    remote = await _load_remote(session, cid)
    if remote is not None and not remote.get("url"):
        return {"remote": None}
    return {"remote": public_remote_view(remote) if remote else None}


@router.post("/containers/{cid}/git/remote/key")
async def remote_key(
    cid: str,
    request: Request,
    rotate: bool = Query(default=False),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Generate (or rotate) the deploy keypair for the container.

    DB-only — works in any container state; keygen is pure CP work.
    Returns {public_key, fingerprint, key_type}.
    """
    await _load_owned_container(session, _tid(principal), cid)
    existing = await _load_remote(session, cid)

    # Return existing key unless rotation is requested.
    if existing and existing.get("ssh_public_key") and not rotate:
        return {
            "public_key": existing["ssh_public_key"],
            "fingerprint": existing["key_fingerprint"],
            "key_type": existing["key_type"],
        }

    keypair = generate_deploy_key()
    master = load_key_from_env()

    from control_plane.auth.crypto import encrypt_secret  # avoid circular at module level

    now = datetime.now(UTC)
    key_cols = {
        "ssh_private_key_ciphertext": encrypt_secret(keypair.private_key, master),
        "ssh_public_key": keypair.public_key,
        "key_type": keypair.key_type,
        "key_fingerprint": keypair.fingerprint,
        "updated_at": now,
    }
    # Insert a stub row if none exists; update key columns on conflict.
    stub = {
        "container_id": cid,
        "url": existing["url"] if existing else "",
        "branch": existing["branch"] if existing else "main",
        "enabled": existing["enabled"] if existing else False,
        "created_at": now,
        **key_cols,
    }
    stmt = pg_insert(git_remotes).values(**stub).on_conflict_do_update(
        index_elements=["container_id"],
        set_=key_cols,
    )
    await session.execute(stmt)
    await session.commit()
    return {
        "public_key": keypair.public_key,
        "fingerprint": keypair.fingerprint,
        "key_type": keypair.key_type,
    }


@router.post("/containers/{cid}/git/remote/verify")
async def verify_remote_route(
    cid: str,
    body: VerifyIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Verify connectivity to the remote using the stored deploy key."""
    crow = await _require_running(session, _tid(principal), cid)
    try:
        url = validate_remote_url(body.url)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "url") from exc

    remote = await _load_remote(session, cid)
    if not remote or not remote.get("ssh_private_key_ciphertext"):
        raise api_error(400, "no_key", "generate a deploy key first")

    key = decrypt_private_key(remote, load_key_from_env())
    async with _shim_for(request, crow) as shim:
        verdict = await _shim_verify(shim, url=url, key=key)

    if not verdict.get("ok"):
        code = verdict.get("error_code")
        raise api_error(400, code or "remote_verify_failed", _verify_message(code))

    return {
        "ok": True,
        "branches": verdict.get("branches", []),
        "default_branch": verdict.get("default_branch"),
    }


@router.put("/containers/{cid}/git/remote")
async def put_remote(
    cid: str,
    body: RemoteIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _require_running(session, _tid(principal), cid)
    try:
        url = validate_remote_url(body.url)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "url") from exc
    try:
        branch = validate_branch(body.branch)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "branch") from exc

    existing = await _load_remote(session, cid)
    if not existing or not existing.get("ssh_private_key_ciphertext"):
        raise api_error(400, "no_key", "generate a deploy key first")

    master = load_key_from_env()
    key = decrypt_private_key(existing, master)

    # Verify the URL+key work before persisting.
    async with _shim_for(request, crow) as shim:
        verdict = await _shim_verify(shim, url=url, key=key)
    if not verdict.get("ok"):
        code = verdict.get("error_code")
        raise api_error(400, code or "remote_verify_failed", _verify_message(code))

    # Reuse the existing keypair — do NOT regenerate.
    keypair = DeployKey(
        private_key=key,
        public_key=existing["ssh_public_key"],
        key_type=existing["key_type"],
        fingerprint=existing["key_fingerprint"],
    )
    values = build_remote_row(
        container_id=cid,
        url=url,
        branch=branch,
        keypair=keypair,
        enabled=body.enabled,
        master_key=master,
    )
    values["verified_at"] = datetime.now(UTC)

    stmt = pg_insert(git_remotes).values(**values).on_conflict_do_update(
        index_elements=["container_id"],
        set_={k: values[k] for k in (
            "url", "branch",
            "ssh_private_key_ciphertext", "ssh_public_key", "key_type", "key_fingerprint",
            "enabled", "verified_at", "updated_at",
        )},
    )
    await session.execute(stmt)
    await session.commit()
    remote = await _load_remote(session, cid)
    return {"remote": public_remote_view(remote)}  # type: ignore[arg-type]


@router.delete("/containers/{cid}/git/remote", status_code=204, response_model=None)
async def delete_remote(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    await _load_owned_container(session, _tid(principal), cid)
    await session.execute(
        git_remotes.delete().where(git_remotes.c.container_id == cid)
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/containers/{cid}/git/push")
async def push_now(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _require_running(session, _tid(principal), cid)
    remote = await _load_remote(session, cid)
    if remote is None or not remote.get("url"):
        raise not_found("no git remote linked")
    key = decrypt_private_key(remote, load_key_from_env())
    async with _shim_for(request, crow) as shim:
        result = await _shim_push(
            shim, url=remote["url"], key=key, branch=remote["branch"]
        )
    await _record_push(session, cid, result)
    if not result.get("ok"):
        raise api_error(
            502, result.get("error_code", "push_failed"),
            result.get("error_message", "push failed"),
        )
    return {"pushed": True, "sha": result.get("sha")}


@router.post("/containers/{cid}/git/rollback")
async def rollback(
    cid: str,
    body: RollbackIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _require_running(session, _tid(principal), cid)
    async with _shim_for(request, crow) as shim:
        try:
            out = await shim.git_rollback(body.sha)
        except ShimGitNotFound:
            raise not_found("unknown snapshot sha") from None
        except ShimGitConflict:
            raise api_error(
                409, "task_running", "cannot roll back while a task is running"
            ) from None
    # Mirror the rollback commit when an enabled remote is linked.
    remote = await _load_remote(session, cid)
    if remote is not None and remote["enabled"]:
        key = decrypt_private_key(remote, load_key_from_env())
        async with _shim_for(request, crow) as shim:
            result = await _shim_push(
                shim, url=remote["url"], key=key, branch=remote["branch"]
            )
        await _record_push(session, cid, result)
    return {"sha": out["sha"]}


# ---- linked-repo (pull mode) routes -------------------------------------------

async def _do_clone(
    request: Request, crow: Any, *, url: str, key: str, branch: str
) -> dict[str, Any]:
    async with _shim_for(request, crow) as shim:
        try:
            return await shim.git_clone(url=url, ssh_private_key=key, branch=branch)
        except httpx.HTTPStatusError as exc:
            # A 404 means the shim has no /git/clone route — i.e. the workspace is
            # running an agent image that predates linked-repo support. Surface a
            # clear, actionable message instead of the generic clone-failure copy.
            if exc.response.status_code == 404:
                raise api_error(
                    502, "agent_outdated",
                    "this workspace is running an older agent image without git "
                    "clone support; create a new workspace to link a repo",
                ) from exc
            # Real clone failure surfaced by the shim as 4xx {"error":{code,message}}.
            code: str | None = None
            try:
                code = exc.response.json().get("error", {}).get("code")
            except Exception:  # noqa: BLE001 — defensive: malformed/empty body
                code = None
            raise api_error(
                400, code or "clone_failed", _verify_message(code)
            ) from exc
        except httpx.HTTPError as exc:
            # Genuine transport failure (shim down/starting/old image).
            raise api_error(
                502, "shim_unreachable",
                "could not reach the agent to clone; try again in a moment",
            ) from exc


@router.post("/containers/{cid}/git/link/key")
async def link_key(
    cid: str,
    request: Request,
    rotate: bool = Query(default=False),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Generate (or rotate) the pull deploy keypair for the container.

    DB-only — works in any container state. Returns {public_key, fingerprint,
    key_type}. Stable across calls unless ?rotate=true.
    """
    await _load_owned_container(session, _tid(principal), cid)
    existing = await _load_linked(session, cid)
    if existing and existing.get("ssh_public_key") and not rotate:
        return {
            "public_key": existing["ssh_public_key"],
            "fingerprint": existing["key_fingerprint"],
            "key_type": existing["key_type"],
        }

    keypair = generate_deploy_key()
    master = load_key_from_env()

    from control_plane.auth.crypto import encrypt_secret  # avoid circular at module level

    now = datetime.now(UTC)
    key_cols = {
        "ssh_private_key_ciphertext": encrypt_secret(keypair.private_key, master),
        "ssh_public_key": keypair.public_key,
        "key_type": keypair.key_type,
        "key_fingerprint": keypair.fingerprint,
        "updated_at": now,
    }
    stub = {
        "container_id": cid,
        "url": existing["url"] if existing else "",
        "branch": existing["branch"] if existing else "main",
        "created_at": now,
        **key_cols,
    }
    stmt = pg_insert(linked_repos).values(**stub).on_conflict_do_update(
        index_elements=["container_id"],
        set_=key_cols,
    )
    await session.execute(stmt)
    await session.commit()
    return {
        "public_key": keypair.public_key,
        "fingerprint": keypair.fingerprint,
        "key_type": keypair.key_type,
    }


@router.post("/containers/{cid}/git/link/verify")
async def link_verify(
    cid: str,
    body: VerifyIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Verify connectivity to the pull remote using the stored deploy key."""
    crow = await _require_running(session, _tid(principal), cid)
    try:
        url = validate_remote_url(body.url)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc), "url") from exc

    linked = await _load_linked(session, cid)
    if not linked or not linked.get("ssh_private_key_ciphertext"):
        raise api_error(400, "no_key", "generate a deploy key first")

    key = decrypt_private_key(linked, load_key_from_env())
    async with _shim_for(request, crow) as shim:
        verdict = await _shim_verify(shim, url=url, key=key)

    if not verdict.get("ok"):
        code = verdict.get("error_code")
        raise api_error(400, code or "remote_verify_failed", _verify_message(code))

    return {
        "ok": True,
        "branches": verdict.get("branches", []),
        "default_branch": verdict.get("default_branch"),
    }


@router.get("/containers/{cid}/git/link")
async def get_link(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _load_owned_container(session, _tid(principal), cid)
    if crow.git_mode != "linked":
        return {"linked": None}
    linked = await _load_linked(session, cid)
    return {"linked": public_linked_view(linked) if linked else None}


async def _link_clone_persist(
    cid: str,
    crow: Any,
    request: Request,
    session: AsyncSession,
    *,
    url: str,
    branch: str,
) -> dict[str, Any]:
    """Shared by link + repull: verify key exists, clone, persist status+mode."""
    linked = await _load_linked(session, cid)
    if not linked or not linked.get("ssh_private_key_ciphertext"):
        raise api_error(400, "no_key", "generate a deploy key first")
    key = decrypt_private_key(linked, load_key_from_env())
    now = datetime.now(UTC)
    try:
        result = await _do_clone(request, crow, url=url, key=key, branch=branch)
    except Exception:
        # Record the failure (and re-raise the api_error so the caller still
        # sees the right 400/502 code).
        await session.execute(
            linked_repos.update().where(linked_repos.c.container_id == cid).values(
                last_clone_status="failed", last_clone_at=now, updated_at=now,
            )
        )
        await session.commit()
        raise

    master = load_key_from_env()
    keypair = DeployKey(
        private_key=key,
        public_key=linked["ssh_public_key"],
        key_type=linked["key_type"],
        fingerprint=linked["key_fingerprint"],
    )
    values = build_linked_row(
        container_id=cid, url=url, branch=branch, keypair=keypair, master_key=master,
    )
    values.update(
        verified_at=now, linked_at=now,
        last_clone_status="cloned", last_clone_error=None, last_clone_at=now,
    )
    await session.execute(
        linked_repos.update().where(linked_repos.c.container_id == cid).values(**{
            k: values[k] for k in (
                "url", "branch", "verified_at", "linked_at",
                "last_clone_status", "last_clone_error", "last_clone_at", "updated_at",
            )
        })
    )
    await _set_git_mode(session, cid, "linked")
    # Exclusivity: a linked container never also pushes snapshots back up.
    await session.execute(
        git_remotes.update().where(git_remotes.c.container_id == cid).values(
            enabled=False, updated_at=now,
        )
    )
    await session.commit()
    _ = result  # sha available if needed later
    linked = await _load_linked(session, cid)
    return {"linked": public_linked_view(linked)}  # type: ignore[arg-type]


@router.post("/containers/{cid}/git/link")
async def post_link(
    cid: str,
    body: LinkIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _require_running(session, _tid(principal), cid)
    if not body.confirm:
        raise api_error(
            400, "confirm_required",
            "linking replaces the workspace; confirm is required",
        )
    try:
        url = validate_remote_url(body.url)
        branch = validate_branch(body.branch)
    except ValueError as exc:
        raise api_error(400, "validation_error", str(exc)) from exc
    await _no_task_running(session, cid)
    return await _link_clone_persist(cid, crow, request, session, url=url, branch=branch)


@router.post("/containers/{cid}/git/link/repull")
async def repull_link(
    cid: str,
    body: RepullIn,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    crow = await _require_running(session, _tid(principal), cid)
    if not body.confirm:
        raise api_error(
            400, "confirm_required",
            "re-pull replaces the workspace; confirm is required",
        )
    linked = await _load_linked(session, cid)
    if not linked or not linked.get("url"):
        raise not_found("no linked repo")
    await _no_task_running(session, cid)
    return await _link_clone_persist(
        cid, crow, request, session, url=linked["url"], branch=linked["branch"],
    )


@router.delete("/containers/{cid}/git/link", status_code=204, response_model=None)
async def delete_link(
    cid: str,
    request: Request,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> Response:
    await _load_owned_container(session, _tid(principal), cid)
    # Keep the linked_repos row (preserves the pull key for a future relink);
    # just flip back to snapshot mode. Files are left exactly as they are.
    await _set_git_mode(session, cid, "snapshot")
    await session.commit()
    return Response(status_code=204)
