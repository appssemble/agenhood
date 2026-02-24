"""drop owner-once: a person may now own multiple tenants.

Removes idx_membership_owner_once (one owned tenant per person). The
one-owner-per-tenant rule (idx_membership_one_owner) stays. This lets a staff
user become the accountable owner of every workspace they create.

Revision ID: 0014_drop_owner_once
Revises: 0013_drop_user_tenant_role
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op

revision = "0014_drop_owner_once"
down_revision = "0013_drop_user_tenant_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_membership_owner_once;")


def downgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX idx_membership_owner_once ON memberships(user_id) "
        "WHERE role = 'owner' AND status = 'active';"
    )
