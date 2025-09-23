from __future__ import annotations

import pytest

from control_plane.users_service import (
    OwnerProtected,
    assert_can_disable_or_delete,
    assert_role_change_allowed,
    new_user_row,
)


def test_cannot_demote_sole_owner() -> None:
    target = {"id": "usr_owner", "role": "owner", "status": "active"}
    with pytest.raises(OwnerProtected):
        assert_role_change_allowed(target, new_role="member", active_owner_count=1)


def test_can_demote_owner_when_another_owner_exists() -> None:
    target = {"id": "usr_owner", "role": "owner", "status": "active"}
    # No exception.
    assert_role_change_allowed(target, new_role="admin", active_owner_count=2)


def test_can_change_non_owner_role() -> None:
    target = {"id": "usr_m", "role": "member", "status": "active"}
    assert_role_change_allowed(target, new_role="admin", active_owner_count=1)


def test_cannot_disable_sole_owner() -> None:
    target = {"id": "usr_owner", "role": "owner", "status": "active"}
    with pytest.raises(OwnerProtected):
        assert_can_disable_or_delete(target, active_owner_count=1)


def test_new_user_row_forces_password_change_and_hashes() -> None:
    row = new_user_row(email="A@B.com", name="A", password="init-pw")
    assert row["email"] == "a@b.com"
    assert row["must_change_password"] is True
    assert row["password_hash"] != "init-pw"
    assert row["is_staff"] is False
    assert "role" not in row
    assert "tenant_id" not in row
