"""Pure helpers for the tenant prompt library (mirrors mcp_service / skills_service).

Variables are inferred from the body; the stored `variables` JSON only carries
optional label/default metadata reconciled against the body on every write.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from control_plane.errors import api_error
from control_plane.ids import new_prompt_id

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

MAX_NAME = 120
MAX_BODY = 20000
MAX_TAGS = 20
MAX_TAG_LEN = 32


def extract_variables(body: str) -> list[str]:
    """Ordered, de-duplicated variable names in first-appearance order."""
    seen: list[str] = []
    for m in _VAR_RE.finditer(body or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def reconcile_variables(body: str, meta: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Canonical variable list derived from `body`, enriched with any matching
    label/default from `meta`. Entries in `meta` whose name no longer appears in
    the body are dropped; names present in the body but missing from `meta` get
    empty label/default."""
    by_name: dict[str, dict[str, Any]] = {}
    for entry in meta or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            by_name[entry["name"]] = entry
    out: list[dict[str, str]] = []
    for name in extract_variables(body):
        src = by_name.get(name, {})
        out.append({
            "name": name,
            "label": str(src.get("label") or ""),
            "default": str(src.get("default") or ""),
        })
    return out


def normalize_tags(raw: Any) -> list[str]:
    """Trim, drop empties, de-dupe case-insensitively (order-preserving, case-preserving).
    Raises on non-list / bad items."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise api_error(400, "validation_error", "tags must be a list of strings", "tags")
    out: list[str] = []
    seen_lower: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise api_error(400, "validation_error", "tags must be a list of strings", "tags")
        t = item.strip()
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            raise api_error(400, "validation_error", f"tag too long (max {MAX_TAG_LEN})", "tags")
        if t.lower() not in seen_lower:
            seen_lower.add(t.lower())
            out.append(t)
    if len(out) > MAX_TAGS:
        raise api_error(400, "validation_error", f"too many tags (max {MAX_TAGS})", "tags")
    return out


def validate_prompt_fields(*, name: str, body: str, tags: list[str]) -> None:
    """Raise APIError(400) on the first invalid field."""
    n = name.strip()
    if not (1 <= len(n) <= MAX_NAME):
        raise api_error(400, "validation_error", f"name must be 1-{MAX_NAME} chars", "name")
    if not (1 <= len(body) <= MAX_BODY):
        raise api_error(400, "validation_error", f"body must be 1-{MAX_BODY} chars", "body")
    # tags already normalized by normalize_tags; nothing further to check.


def build_prompt_row(
    *, tenant_id: str, created_by: str | None, name: str, body: str,
    tags: list[str], variables: list[dict[str, str]],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_prompt_id(),
        "tenant_id": tenant_id,
        "name": name.strip(),
        "body": body,
        "tags": tags,
        "variables": variables,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def prompt_view(row: dict[str, Any]) -> dict[str, Any]:
    """API view — tenant_id is never exposed."""
    return {
        "id": row["id"],
        "name": row["name"],
        "body": row["body"],
        "tags": list(row.get("tags") or []),
        "variables": list(row.get("variables") or []),
        "created_by": row.get("created_by"),
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
    }


def resolve_body(
    body: str,
    values: dict[str, str] | None,
    variables: list[dict[str, Any]] | None,
) -> str:
    """Fill ``{{name}}`` placeholders for submit-by-prompt.

    Caller ``values`` override each variable's stored ``default``; a placeholder
    that resolves to an empty string (or is unknown) is left verbatim. Mirrors the
    console ``resolve()`` in web/console/src/lib/prompts.ts (``value !== ""``).
    """
    effective: dict[str, str] = {}
    for v in variables or []:
        if isinstance(v, dict) and isinstance(v.get("name"), str):
            effective[v["name"]] = str(v.get("default") or "")
    for name, val in (values or {}).items():
        effective[name] = str(val)

    def _sub(m: "re.Match[str]") -> str:
        repl = effective.get(m.group(1))
        return repl if repl else m.group(0)

    return _VAR_RE.sub(_sub, body or "")
