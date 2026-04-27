"""workflows + workflow_runs: reusable multi-container prompt queues

Revision ID: 0019_workflows
Revises: 0018_unfreeze_allowed_drivers
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0019_workflows"
down_revision = "0018_unfreeze_allowed_drivers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workflows (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            name        TEXT NOT NULL,
            description TEXT,
            steps       JSONB NOT NULL,
            created_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE UNIQUE INDEX idx_workflows_tenant_name ON workflows(tenant_id, name)")
    op.execute(
        """
        CREATE TABLE workflow_runs (
            id                TEXT PRIMARY KEY,
            workflow_id       TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            tenant_id         TEXT NOT NULL,
            status            TEXT NOT NULL,
            cursor            INTEGER NOT NULL DEFAULT 0,
            current_task_id   TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            step_count        INTEGER NOT NULL,
            error_step        INTEGER,
            error_message     TEXT,
            trigger_source    TEXT NOT NULL,
            scheduled_task_id TEXT REFERENCES scheduled_tasks(id) ON DELETE SET NULL,
            started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            step_started_at   TIMESTAMPTZ,
            ended_at          TIMESTAMPTZ
        );
        """
    )
    op.execute("CREATE INDEX idx_wfr_active ON workflow_runs(workflow_id) WHERE status = 'running'")
    op.execute(
        "CREATE INDEX idx_wfr_schedule ON workflow_runs(scheduled_task_id) "
        "WHERE scheduled_task_id IS NOT NULL AND status = 'running'"
    )
    op.execute("CREATE INDEX idx_wfr_history ON workflow_runs(workflow_id, started_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_runs")
    op.execute("DROP TABLE IF EXISTS workflows")
