"""unit4: lifecycle/timing columns and dormant/transient indexes

Revision ID: 0004_unit4_lifecycle_columns
Revises: 0003_unit3_tenancy_auth
Create Date: 2026-05-20
"""
from alembic import op

revision = "0004_unit4_lifecycle_columns"
down_revision = "0003_unit3_tenancy_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Audit/timing columns — new in Unit 4; added idempotently.
    op.execute("ALTER TABLE containers ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ")
    op.execute("ALTER TABLE containers ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ")
    op.execute("ALTER TABLE containers ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ")

    # Columns the Unit 2 baseline should already have; added defensively in case
    # an older baseline lacked them (IF NOT EXISTS is a no-op when they exist).
    op.execute(
        "ALTER TABLE containers ADD COLUMN IF NOT EXISTS "
        "image_variant TEXT NOT NULL DEFAULT 'full'"
    )
    op.execute(
        "ALTER TABLE containers ADD COLUMN IF NOT EXISTS "
        "recovery_attempts INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE containers ADD COLUMN IF NOT EXISTS "
        "destroy_delete_volume BOOLEAN"
    )
    op.execute(
        "ALTER TABLE containers ADD COLUMN IF NOT EXISTS "
        "status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )

    # Dormant sweep index (paused→archive, archived→reclaim keyed on status_changed_at).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_containers_dormant "
        "ON containers (status, status_changed_at) "
        "WHERE status IN ('paused','archived')"
    )
    # Transient-stuck index for the reconciler.
    _transient_states = (
        "('provisioning','resuming','pausing','archiving','recovering','destroying')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_containers_transient "
        "ON containers (status, status_changed_at) "
        f"WHERE status IN {_transient_states}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_containers_transient")
    op.execute("DROP INDEX IF EXISTS idx_containers_dormant")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS archived_at")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS paused_at")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS last_active_at")
    # Leave image_variant/recovery_attempts/destroy_delete_volume/status_changed_at:
    # they belong to the Unit 2 baseline; downgrading this revision must not drop them.
