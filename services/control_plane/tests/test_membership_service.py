from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_memberships_table_registered_with_expected_columns():
    import control_plane.tables as t

    cols = set(t.memberships.c.keys())
    assert cols == {
        "id", "user_id", "tenant_id", "role", "status", "created_at", "updated_at",
    }


def test_sessions_has_active_tenant_id_column():
    import control_plane.tables as t

    assert "active_tenant_id" in t.sessions.c.keys()


def test_new_membership_row_defaults():
    from control_plane.membership_service import new_membership_row

    row = new_membership_row(user_id="usr_1", tenant_id="ten_1", role="admin")
    assert row["user_id"] == "usr_1"
    assert row["tenant_id"] == "ten_1"
    assert row["role"] == "admin"
    assert row["status"] == "active"
    assert row["id"].startswith("mbr_")
    assert row["created_at"] is not None and row["updated_at"] is not None


def test_new_membership_row_rejects_bad_role():
    from control_plane.membership_service import new_membership_row

    with pytest.raises(ValueError):
        new_membership_row(user_id="u", tenant_id="t", role="superuser")


def test_owner_conflict_message_distinguishes_indexes():
    from control_plane.membership_service import owner_conflict_message

    assert owner_conflict_message(
        'duplicate key value violates unique constraint "idx_membership_owner_once"'
    ) == "This user already owns another workspace"
    assert owner_conflict_message(
        'duplicate key value violates unique constraint "idx_membership_one_owner"'
    ) == "This workspace already has an owner"
    assert owner_conflict_message("some other error") == "Membership conflict"


def test_default_active_tenant_prefers_owner():
    from control_plane.membership_service import default_active_tenant

    memberships = [
        {"tenant_id": "ten_a", "role": "member"},
        {"tenant_id": "ten_b", "role": "owner"},
    ]
    assert default_active_tenant(memberships) == "ten_b"


def test_default_active_tenant_falls_back_to_first():
    from control_plane.membership_service import default_active_tenant

    memberships = [
        {"tenant_id": "ten_a", "role": "member"},
        {"tenant_id": "ten_b", "role": "admin"},
    ]
    assert default_active_tenant(memberships) == "ten_a"


def test_default_active_tenant_empty_is_none():
    from control_plane.membership_service import default_active_tenant

    assert default_active_tenant([]) is None


def test_metadata_has_no_owner_once_index():
    import control_plane.tables as t

    names = {ix.name for ix in t.memberships.indexes}
    assert "idx_membership_owner_once" not in names
    assert "idx_membership_one_owner" in names
