"""Tenant skill library CRUD (spec: opencode skills). Returns raw dicts like
the templates router. Writes are admin-gated; reads are tenant-scoped."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field
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

router = APIRouter(tags=["Skills"])

_PATCHABLE = {"name", "description", "body", "enabled"}


# ---- response models (documentation only) -----------------------------------

class SkillListResponse(BaseModel):
    """Envelope returned by ``GET /skills``."""

    skills: list[dict[str, Any]] = Field(
        description="The tenant's skills in summary form (no body/bundle bytes), "
        "sorted by name."
    )


class SkillGitRefsResponse(BaseModel):
    """Branch listing for a remote skill repository (create-form picker)."""

    ok: bool = Field(description="Always true on success.")
    branches: list[str] = Field(
        description="Branch names discovered in the remote repository."
    )
    default_branch: str | None = Field(
        description="The repository's default branch, if one could be resolved."
    )

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

@router.get(
    "/skills",
    response_model=SkillListResponse,
    response_description="The tenant's skills in summary form.",
)
async def list_skills(
    request: Request, principal: Principal = Depends(resolve_principal)
) -> dict[str, Any]:
    """List all skills owned by the caller's tenant.

    Tenant-scoped read (any authenticated member/API key). Returns summary rows
    only — the full ``body`` and the packed git bundle bytes are omitted. Sorted
    by name.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(*_LIST_COLS).where(skills.c.tenant_id == principal.tenant_id)
            .order_by(skills.c.name)
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    return {"skills": [skill_public_view(r) for r in rows]}


@router.get(
    "/skills/{sid}",
    response_description="The full skill, including its body.",
)
async def get_skill(
    sid: Annotated[str, Path(description="Skill id.")],
    request: Request,
    principal: Principal = Depends(resolve_principal),
) -> dict[str, Any]:
    """Fetch a single skill by id, including its full ``body``.

    Tenant-scoped read (any authenticated member/API key); a skill belonging to
    another tenant is treated as absent. Returns ``404 not_found`` if no such
    skill exists for the tenant.
    """
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


@router.post(
    "/skills/git-refs",
    response_model=SkillGitRefsResponse,
    response_description="The remote repository's branches and default branch.",
)
async def list_skill_git_refs(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """List a remote git repository's branches for the create-form picker.

    Admin-only. Read-only lookup: no skill is created. Body must contain
    ``source_url``. Returns the branch names plus the resolved default branch.
    Errors: ``400 validation_error`` if ``source_url`` is missing; ``422
    validation_error`` if the URL is rejected (bad scheme, e.g. ``file://``);
    ``502 skill_refs_error`` if the remote is unreachable or private.
    """
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


@router.post(
    "/skills",
    response_description="The created skill, including its body.",
)
async def create_skill(
    request: Request, principal: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """Create a skill from an inline body or a remote git source.

    Admin-only and tenant-scoped. Body ``source_type`` selects the mode:
    ``inline`` (default) requires ``name`` and ``description`` (plus optional
    ``body``); ``git`` requires ``source_url`` and ``source_ref`` (optional
    ``source_subpath``), and the name/description/body are derived from the
    fetched ``SKILL.md``, which is packed into a cached bundle. Errors:
    ``403 forbidden`` for a staff principal with no tenant; ``400
    validation_error`` for a malformed payload; ``422 skill_fetch_error`` if the
    git source cannot be fetched/packed; ``409 conflict`` if a skill of that
    name already exists for the tenant.
    """
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


@router.patch(
    "/skills/{sid}",
    response_description="The updated skill, including its body.",
)
async def patch_skill(
    sid: Annotated[str, Path(description="Skill id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Update an existing skill (partial patch).

    Admin-only and tenant-scoped. For inline skills, ``name``, ``description``,
    ``body`` and ``enabled`` may be patched. For git skills only ``enabled`` may
    be toggled — changing name/description/body would desync the stored name
    from the bundle's ``SKILL.md`` folder, so those fields are ignored. Errors:
    ``404 not_found`` if the skill does not exist for the tenant; ``409
    conflict`` if a rename collides with another skill's name.
    """
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


@router.post(
    "/skills/{sid}/refresh",
    response_description="The refreshed skill, re-pinned to the latest SHA.",
)
async def refresh_skill(
    sid: Annotated[str, Path(description="Skill id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Re-pin a git skill to the latest commit of its source ref.

    Admin-only and tenant-scoped. Re-resolves the stored ``source_ref`` to a new
    SHA, re-fetches and re-packs the bundle, and replaces the cached name,
    description, body, pinned SHA and bundle bytes. Errors: ``404 not_found`` if
    the skill does not exist for the tenant; ``400 validation_error`` if the
    skill is not a git skill (inline skills cannot be refreshed); ``422
    skill_fetch_error`` if the source cannot be re-fetched.
    """
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


@router.delete(
    "/skills/{sid}",
    status_code=204,
    response_description="Skill deleted; no content returned.",
)
async def delete_skill(
    sid: Annotated[str, Path(description="Skill id.")],
    request: Request,
    principal: Principal = Depends(require_admin),
) -> None:
    """Delete a skill by id.

    Admin-only and tenant-scoped. Returns ``204 No Content`` on success.
    Returns ``404 not_found`` if no such skill exists for the tenant.
    """
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
