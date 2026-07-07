"""container resource limits: mem_limit + cpus per container

Revision ID: 0024_container_resource_limits
Revises: 0023_task_session_id
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op

revision = "0024_container_resource_limits"
down_revision = "0023_task_session_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE containers ADD COLUMN mem_limit TEXT NOT NULL DEFAULT '4g'")
    op.execute(
        "ALTER TABLE containers ADD COLUMN cpus DOUBLE PRECISION NOT NULL DEFAULT 2.0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS cpus")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS mem_limit")
