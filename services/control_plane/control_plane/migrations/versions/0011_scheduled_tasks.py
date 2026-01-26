"""scheduled tasks: scheduled_tasks table + tasks.scheduled_task_id

Revision ID: 0011_scheduled_tasks
Revises: 0010_git_remote_ssh
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op

revision = "0011_scheduled_tasks"
down_revision = "0010_git_remote_ssh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scheduled_tasks (
            id            TEXT PRIMARY KEY,
            tenant_id     TEXT NOT NULL REFERENCES tenants(id),
            container_id  TEXT NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            driver        TEXT NOT NULL,
            model         TEXT,
            task_body     JSONB NOT NULL,
            schedule      JSONB NOT NULL,
            timezone      TEXT NOT NULL,
            enabled       BOOLEAN NOT NULL DEFAULT true,
            next_run_at   TIMESTAMPTZ,
            last_run_at   TIMESTAMPTZ,
            last_task_id  TEXT,
            last_status   TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_scheduled_tasks_container "
        "ON scheduled_tasks (container_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_scheduled_tasks_due ON scheduled_tasks (next_run_at) "
        "WHERE enabled AND next_run_at IS NOT NULL"
    )
    op.execute("ALTER TABLE tasks ADD COLUMN scheduled_task_id TEXT")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT fk_tasks_scheduled_task "
        "FOREIGN KEY (scheduled_task_id) REFERENCES scheduled_tasks(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX idx_tasks_scheduled ON tasks (scheduled_task_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_scheduled")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_scheduled_task")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS scheduled_task_id")
    op.execute("DROP TABLE IF EXISTS scheduled_tasks")
