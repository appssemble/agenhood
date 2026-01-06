# services/control_plane/control_plane/skills_service.py
"""Pure helpers for the opencode skill library (spec: opencode skills).

Validation mirrors opencode's own rules so a stored skill can never fail to
load. Resolution maps selected ids → ShimSkill content for the task request.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any

from agentcore.drivers.skills_md import (
    MAX_BUNDLE_BYTES as MAX_BUNDLE_BYTES,
)
from agentcore.drivers.skills_md import (
    MAX_BUNDLE_FILES as MAX_BUNDLE_FILES,
)
from agentcore.drivers.skills_md import (
    MAX_DESCRIPTION,
    MAX_NAME,
    valid_skill_name,
)
from agentcore.models import ShimSkill
from control_plane.errors import api_error
from control_plane.ids import new_skill_id
from control_plane.skills_fetch import FetchedSkill

MAX_BODY = 64 * 1024
MAX_TASK_BUNDLE_BYTES = 20 * 1024 * 1024

log = logging.getLogger(__name__)


def normalize_description(description: str) -> str:
    """Collapse newlines/runs of whitespace to single spaces and trim.

    The spec requires descriptions to be single-line (they become a YAML
    frontmatter scalar); we normalize at the API/storage boundary so the stored
    value is exactly what loads, rather than relying on render-time collapsing."""
    return " ".join(description.split())


def validate_skill_fields(*, name: str, description: str, body: str) -> None:
    """Raise APIError(400) on the first invalid field."""
    if not valid_skill_name(name):
        raise api_error(
            400, "validation_error",
            f"name must match ^[a-z0-9]+(-[a-z0-9]+)*$ and be 1-{MAX_NAME} chars",
            "name",
        )
    if not (1 <= len(description) <= MAX_DESCRIPTION):
        raise api_error(
            400, "validation_error",
            f"description must be 1-{MAX_DESCRIPTION} chars", "description",
        )
    if len(body) > MAX_BODY:
        raise api_error(
            400, "validation_error", f"body exceeds {MAX_BODY} bytes", "body",
        )


def build_skill_row(
    *,
    tenant_id: str,
    name: str,
    description: str,
    body: str,
    enabled: bool,
    created_by: str | None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_skill_id(),
        "tenant_id": tenant_id,
        "name": name,
        "description": description,
        "body": body,
        "enabled": enabled,
        "source_type": "inline",
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def build_git_skill_row(
    *,
    tenant_id: str,
    created_by: str | None,
    enabled: bool,
    source_url: str,
    source_subpath: str,
    source_ref: str,
    fetched: FetchedSkill,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_skill_id(),
        "tenant_id": tenant_id,
        "name": fetched.name,
        "description": normalize_description(fetched.description),
        "body": fetched.body,
        "enabled": enabled,
        "source_type": "git",
        "source_url": source_url,
        "source_subpath": source_subpath,
        "source_ref": source_ref,
        "pinned_sha": fetched.pinned_sha,
        "bundle": fetched.bundle,
        "bundle_sha256": fetched.bundle_sha256,
        "bundle_size": fetched.bundle_size,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def skill_public_view(row: dict[str, Any]) -> dict[str, Any]:
    """List/summary view — tenant_id and the (potentially large) body/bundle
    bytes stripped. Source/pin metadata is included so the console can show
    where a git skill came from."""
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "enabled": row["enabled"],
        "source_type": row.get("source_type", "inline"),
        "source_url": row.get("source_url"),
        "source_subpath": row.get("source_subpath"),
        "source_ref": row.get("source_ref"),
        "pinned_sha": row.get("pinned_sha"),
        "bundle_size": row.get("bundle_size"),
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
    }


def skill_detail_view(row: dict[str, Any]) -> dict[str, Any]:
    """Single-skill view — the summary plus the full ``body``."""
    return {**skill_public_view(row), "body": row["body"]}


def resolve_skills_for_request(
    selected_ids: list[str], rows: list[dict[str, Any]]
) -> list[ShimSkill]:
    """Map selected skill ids → ShimSkill content, preserving selection order,
    keeping only enabled rows that belong to the tenant. Git rows ship the
    cached bundle as base64; inline rows ship the body. The summed uncompressed
    bundle size is capped per task (MAX_TASK_BUNDLE_BYTES); skills that would
    push the total over the cap are dropped in selection order and logged
    (never silently)."""
    by_id = {r["id"]: r for r in rows if r.get("enabled")}
    out: list[ShimSkill] = []
    budget = MAX_TASK_BUNDLE_BYTES
    for sid in selected_ids:
        r = by_id.get(sid)
        if r is None:
            continue
        if r.get("source_type") == "git" and r.get("bundle"):
            size = r.get("bundle_size") or 0
            if size > budget:
                log.warning(
                    "skill %s dropped from task: bundle cap exceeded",
                    r.get("name"),
                )
                continue
            budget -= size
            raw = bytes(r["bundle"])
            out.append(ShimSkill(
                name=r["name"], description=r["description"],
                bundle_b64=base64.b64encode(raw).decode(),
            ))
        else:
            out.append(ShimSkill(
                name=r["name"], description=r["description"],
                body=r.get("body", "") or "",
            ))
    return out


def filter_known_skill_ids(
    selected_ids: list[str], rows: list[dict[str, Any]]
) -> list[str]:
    """Drop ids that don't belong to the tenant, preserving selection order."""
    known = {r["id"] for r in rows}
    return [sid for sid in selected_ids if sid in known]
