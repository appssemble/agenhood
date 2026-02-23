"""unit: drop legacy users.tenant_id / users.role — CONTRACT phase.

Run only after 0012 + membership-aware code have soaked. Downgrade re-adds the
columns and backfills from the owner/most-recent membership.

Revision ID: 0013_drop_user_tenant_role
Revises: 0012_user_memberships
Create Date: 2026-06-18
"""
from __future__ import annotations

from alembic import op

revision = "0013_drop_user_tenant_role"
down_revision = "0012_user_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_one_owner;")
    op.execute("DROP INDEX IF EXISTS idx_users_tenant;")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS staff_has_no_tenant;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tenant_id;")


def downgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN tenant_id TEXT REFERENCES tenants(id);")
    op.execute("ALTER TABLE users ADD COLUMN role TEXT;")
    op.execute("""
        UPDATE users u SET tenant_id = m.tenant_id, role = m.role
        FROM (
            SELECT DISTINCT ON (user_id) user_id, tenant_id, role
            FROM memberships WHERE status = 'active'
            ORDER BY user_id, (role = 'owner') DESC, created_at ASC
        ) m
        WHERE u.id = m.user_id AND u.is_staff = false;
    """)
    op.execute("UPDATE users SET role = 'member' WHERE role IS NULL;")
    op.execute("ALTER TABLE users ALTER COLUMN role SET NOT NULL;")
    op.execute("CREATE INDEX idx_users_tenant ON users(tenant_id);")
    op.execute("""
        CREATE UNIQUE INDEX idx_users_one_owner ON users(tenant_id)
            WHERE role = 'owner' AND status = 'active';
    """)
