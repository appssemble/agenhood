"""Tenant skill library CRUD (spec: opencode skills). Returns raw dicts like
the templates router. Writes are admin-gated; reads are tenant-scoped."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from control_plane.auth.principal import (
    Principal,
    require_admin,
    resolve_principal,
)
from control_plane.errors import api_error, not_found
from control_plane.models_db import skills
from control_plane.skills_fetch import fetch_git_skill, list_branches
from control_plane.skills_service import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    build_git_skill_row,
    build_skill_row,
    normalize_description,
    skill_detail_view,
    skill_public_view,
    validate_skill_fields,
)

router = APIRouter()

_PATCHABLE = {"name", "description", "body", "enabled"}

# Columns selected on read paths — bundle (BYTEA) and bundle_sha256 are excluded
# so large binary data is never transferred for list/detail views.
_LIST_COLS = [
    skills.c.id, skills.c.tenant_id, skills.c.name, skills.c.description,
    skills.c.source_type, skills.c.source_url, skills.c.source_subpath,
    skills.c.source_ref, skills.c.pinned_sha, skills.c.bundle_size,
    skills.c.enabled, skills.c.created_by, skills.c.created_at, skills.c.updated_at,
]
_DETAIL_COLS = [*_LIST_COLS, skills.c.body]


# ---- pure helpers (unit-tested) --------------------------------------------

def parse_skill_create(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a create payload → normalized field dict.

    ``source_type`` 'inline' (default) validates name/description/body as before.
    'git' validates source_url/source_subpath/source_ref; the actual name/
    description/body are derived later from the fetched SKILL.md."""
    source_type = body.get("source_type", "inline")
    enabled = bool(body.get("enabled", True))
    if source_type == "git":
        url = body.get("source_url")
        ref = body.get("source_ref")
        if not isinstance(url, str) or not url:
            raise api_error(400, "validation_error", "source_url is required", "source_url")
        if not isinstance(ref, str) or not ref:
            raise api_error(400, "validation_error", "source_ref is required", "source_ref")
        return {
            "source_type": "git",
            "source_url": url,
            "source_subpath": str(body.get("source_subpath", "") or ""),
            "source_ref": ref,
            "enabled": enabled,
        }
    # inline (default)
    name = body.get("name")
    description = body.get("description")
    if not isinstance(name, str):
        raise api_error(400, "validation_error", "name is required", "name")
    if not isinstance(description, str):
        raise api_error(400, "validation_error", "description is required", "description")
    description = normalize_description(description)
    skill_body = body.get("body", "") or ""
    validate_skill_fields(name=name, description=description, body=skill_body)
    return {"name": name, "description": description, "body": skill_body,
            "enabled": enabled, "source_type": "inline"}


def apply_skill_patch(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a PATCH onto the existing fields and re-validate."""
    merged = {k: existing.get(k) for k in ("name", "description", "body", "enabled")}
    for k, v in patch.items():
        if k in _PATCHABLE:
            merged[k] = v
    if "description" in patch:
        merged["description"] = normalize_description(str(merged["description"]))
    validate_skill_fields(
        name=str(merged["name"]), description=str(merged["description"]),
        body=str(merged["body"] or ""),
    )
    merged["enabled"] = bool(merged["enabled"])
    return merged


# ---- routes -----------------------------------------------------------------

@router.get("/skills")
async def list_skills(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_LIST_COLS).where(skills.c.tenant_id == principal.tenant_id)
            .order_by(skills.c.name)
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    return {"skills": [skill_public_view(r) for r in rows]}


@router.get("/skills/{sid}")
async def get_skill(
    sid: str, request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_DETAIL_COLS).where(
                skills.c.id == sid, skills.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
    if row is None:
        raise not_found("skill not found")
    return skill_detail_view(dict(row._mapping))


@router.post("/skills/git-refs")
async def list_skill_git_refs(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """List a remote repo's branches (+ default) for the create form's branch
    picker. Read-only: no skill is created. A rejected URL (bad scheme) is a 422
    validation error; an unreachable/private remote is a 502."""
    body = await request.json()
    url = body.get("source_url")
    if not isinstance(url, str) or not url:
        raise api_error(400, "validation_error", "source_url is required", "source_url")
    try:
        branches, default_branch = await asyncio.to_thread(list_branches, url)
    except ValueError as exc:
        msg = str(exc)
        bad_url = "source_url must be" in msg or "file://" in msg
        raise api_error(
            422 if bad_url else 502,
            "validation_error" if bad_url else "skill_refs_error",
            msg, "source_url",
        ) from exc
    return {"ok": True, "branches": branches, "default_branch": default_branch}


@router.post("/skills")
async def create_skill(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if principal.tenant_id is None:
        raise api_error(403, "forbidden", "Skills are tenant-scoped")
    fields = parse_skill_create(await request.json())

    if fields["source_type"] == "git":
        try:
            fetched = await asyncio.to_thread(
                fetch_git_skill,
                url=fields["source_url"], subpath=fields["source_subpath"],
                ref=fields["source_ref"],
                max_files=MAX_BUNDLE_FILES, max_bytes=MAX_BUNDLE_BYTES,
            )
        except ValueError as exc:
            raise api_error(422, "skill_fetch_error", str(exc), "source_url") from exc
        row = build_git_skill_row(
            tenant_id=principal.tenant_id, created_by=principal.user_id,
            enabled=fields["enabled"], source_url=fields["source_url"],
            source_subpath=fields["source_subpath"], source_ref=fields["source_ref"],
            fetched=fetched,
        )
    else:
        row = build_skill_row(
            tenant_id=principal.tenant_id, created_by=principal.user_id,
            name=fields["name"], description=fields["description"],
            body=fields["body"], enabled=fields["enabled"],
        )

    async with request.app.state.session_factory() as session:
        dupe = await session.execute(
            select(skills.c.id).where(
                skills.c.tenant_id == principal.tenant_id,
                skills.c.name == row["name"],
            )
        )
        if dupe.fetchone() is not None:
            raise api_error(
                409, "conflict", f"a skill named {row['name']!r} already exists", "name"
            )
        await session.execute(skills.insert().values(**row))
        await session.commit()
    return skill_detail_view(row)


@router.patch("/skills/{sid}")
async def patch_skill(
    sid: str, request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    patch = await request.json()
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_DETAIL_COLS).where(
                skills.c.id == sid, skills.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("skill not found")
        existing = dict(row._mapping)
        now = datetime.now(UTC)
        if existing.get("source_type") == "git":
            # Git skills: only enabled may be toggled. Changing name/description/body
            # would desync the stored name from the bundle's SKILL.md folder name.
            update_values = {
                "enabled": bool(patch.get("enabled", existing["enabled"])),
                "updated_at": now,
            }
            await session.execute(
                skills.update().where(skills.c.id == sid).values(**update_values)
            )
            await session.commit()
            existing.update(update_values)
        else:
            merged = apply_skill_patch(existing, patch)
            if merged["name"] != existing["name"]:
                dupe = await session.execute(
                    select(skills.c.id).where(
                        skills.c.tenant_id == principal.tenant_id,
                        skills.c.name == merged["name"],
                        skills.c.id != sid,
                    )
                )
                if dupe.fetchone() is not None:
                    raise api_error(
                        409, "conflict",
                        f"a skill named {merged['name']!r} already exists", "name",
                    )
            await session.execute(
                skills.update().where(skills.c.id == sid).values(
                    **merged, updated_at=now
                )
            )
            await session.commit()
            existing.update(merged)
    return skill_detail_view(existing)


@router.post("/skills/{sid}/refresh")
async def refresh_skill(
    sid: str, request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Re-pin a git skill: re-resolve its source_ref → new SHA, re-fetch/pack,
    replace the cached bundle. Inline skills cannot be refreshed."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(skills).where(
                skills.c.id == sid, skills.c.tenant_id == principal.tenant_id
            )
        )
        row = result.fetchone()
        if row is None:
            raise not_found("skill not found")
        existing = dict(row._mapping)
        if existing.get("source_type") != "git":
            raise api_error(400, "validation_error", "only git skills can be refreshed")
        try:
            fetched = await asyncio.to_thread(
                fetch_git_skill,
                url=existing["source_url"],
                subpath=existing["source_subpath"] or "",
                ref=existing["source_ref"],
                max_files=MAX_BUNDLE_FILES, max_bytes=MAX_BUNDLE_BYTES,
            )
        except ValueError as exc:
            raise api_error(422, "skill_fetch_error", str(exc), "source_url") from exc
        values = {
            "name": fetched.name,
            "description": normalize_description(fetched.description),
            "body": fetched.body,
            "pinned_sha": fetched.pinned_sha,
            "bundle": fetched.bundle,
            "bundle_sha256": fetched.bundle_sha256,
            "bundle_size": fetched.bundle_size,
            "updated_at": datetime.now(UTC),
        }
        await session.execute(
            skills.update().where(
                skills.c.id == sid,
                skills.c.tenant_id == principal.tenant_id,
            ).values(**values)
        )
        await session.commit()
        existing.update(values)
    return skill_detail_view(existing)


@router.delete("/skills/{sid}", status_code=204)
async def delete_skill(
    sid: str, request: Request, principal: Principal = Depends(require_admin)
) -> None:
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(skills.c.id).where(
                skills.c.id == sid, skills.c.tenant_id == principal.tenant_id
            )
        )
        if result.fetchone() is None:
            raise not_found("skill not found")
        await session.execute(skills.delete().where(skills.c.id == sid))
        await session.commit()
