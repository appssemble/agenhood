"""unit: user memberships (multi-tenant users) — EXPAND phase.

Adds memberships(user_id, tenant_id, role), backfills one membership per
non-staff user, and adds sessions.active_tenant_id. Keeps users.tenant_id and
users.role in place so the previous code revision still runs (rollback-safe).
The contract migration 0013 drops them later.

Revision ID: 0012_user_memberships
Revises: 0011_scheduled_tasks
Create Date: 2026-06-18
"""
from __future__ import annotations

from alembic import op

revision = "0012_user_memberships"
down_revision = "0011_scheduled_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memberships (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_membership UNIQUE (user_id, tenant_id)
        );
    """)
    op.execute("CREATE INDEX idx_memberships_user   ON memberships(user_id);")
    op.execute("CREATE INDEX idx_memberships_tenant ON memberships(tenant_id);")
    op.execute("""
        CREATE UNIQUE INDEX idx_membership_one_owner ON memberships(tenant_id)
            WHERE role = 'owner' AND status = 'active';
    """)
    op.execute("""
        CREATE UNIQUE INDEX idx_membership_owner_once ON memberships(user_id)
            WHERE role = 'owner' AND status = 'active';
    """)
    op.execute("""
        INSERT INTO memberships (id, user_id, tenant_id, role, status, created_at, updated_at)
        SELECT 'mbr_' || u.id, u.id, u.tenant_id, u.role, u.status, now(), now()
        FROM users u
        WHERE u.tenant_id IS NOT NULL AND u.is_staff = false;
    """)
    op.execute("ALTER TABLE sessions ADD COLUMN active_tenant_id TEXT REFERENCES tenants(id);")
    op.execute("""
        UPDATE sessions s SET active_tenant_id = u.tenant_id
        FROM users u
        WHERE s.user_id = u.id AND u.tenant_id IS NOT NULL AND u.is_staff = false;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS active_tenant_id;")
    op.execute("DROP TABLE IF EXISTS memberships;")
