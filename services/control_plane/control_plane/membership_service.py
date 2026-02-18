from __future__ import annotations

from datetime import UTC, datetime

from control_plane.ids_compat import new_id

VALID_ROLES = ("owner", "admin", "member")


def new_membership_row(
    *,
    user_id: str,
    tenant_id: str,
    role: str,
    status: str = "active",
) -> dict:  # type: ignore[type-arg]
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    now = datetime.now(UTC)
    return {
        "id": new_id("mbr"),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }


def default_active_tenant(memberships: list[dict]) -> str | None:  # type: ignore[type-arg]
    """Deterministic fallback tenant when there's no recent-session memory.

    Prefers the tenant the user owns; else the first membership (the login query
    orders memberships by tenant_id, so this is the first alphabetically).
    """
    if not memberships:
        return None
    for m in memberships:
        if m["role"] == "owner":
            return m["tenant_id"]
    return memberships[0]["tenant_id"]


def owner_conflict_message(error_text: str) -> str:
    """Map a Postgres unique-violation message to a human-facing reason."""
    if "idx_membership_owner_once" in error_text:
        return "This user already owns another workspace"
    if "idx_membership_one_owner" in error_text:
        return "This workspace already has an owner"
    return "Membership conflict"
