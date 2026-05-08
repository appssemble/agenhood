"""workflow_events: per-run event stream (started/step_advanced/completed/failed)

Revision ID: 0022_workflow_events
Revises: 0021_workflow_run_steps
Create Date: 2026-06-29
"""
from alembic import op

revision = "0022_workflow_events"
down_revision = "0021_workflow_run_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_events (
            run_id  TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
            seq     INTEGER NOT NULL,
            type    TEXT NOT NULL,
            payload JSONB NOT NULL,
            ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id, seq)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_events")
