"""workflow_runs.steps: per-step run timeline (task id + status + start/end)

Revision ID: 0021_workflow_run_steps
Revises: 0020_scheduled_tasks_targets
Create Date: 2026-06-29
"""
from alembic import op

revision = "0021_workflow_run_steps"
down_revision = "0020_scheduled_tasks_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS steps JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS steps")
