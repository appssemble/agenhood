"""driver sessions: tasks.session_id groups tasks into a shared conversation

Revision ID: 0023_task_session_id
Revises: 0022_workflow_events
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op

revision = "0023_task_session_id"
down_revision = "0022_workflow_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
    op.execute("CREATE INDEX idx_tasks_session ON tasks (session_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_session")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS session_id")
