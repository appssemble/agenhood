from __future__ import annotations

from datetime import UTC, datetime

from control_plane.auth.passwords import hash_password
from control_plane.ids_compat import new_id


class OwnerProtected(Exception):
    """Raised when an action would remove/demote the sole active owner."""


def assert_role_change_allowed(
    target: dict,  # type: ignore[type-arg]
    *,
    new_role: str,
    active_owner_count: int,
) -> None:
    if target["role"] == "owner" and new_role != "owner" and active_owner_count <= 1:
        raise OwnerProtected("Cannot demote the sole owner")


def assert_can_disable_or_delete(
    target: dict,  # type: ignore[type-arg]
    *,
    active_owner_count: int,
) -> None:
    if target["role"] == "owner" and active_owner_count <= 1:
        raise OwnerProtected("Cannot disable or delete the sole owner")


def new_user_row(
    *,
    email: str,
    name: str,
    password: str,
) -> dict:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    return {
        "id": new_id("usr"),
        "email": email.lower(),
        "name": name,
        "password_hash": hash_password(password),
        "is_staff": False,
        "must_change_password": True,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
