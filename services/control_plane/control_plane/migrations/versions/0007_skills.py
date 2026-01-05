"""opencode skills: skills table

Revision ID: 0007_skills
Revises: 0006_git_remotes
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op

revision = "0007_skills"
down_revision = "0006_git_remotes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE skills (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            name        TEXT NOT NULL,
            description TEXT NOT NULL,
            body        TEXT NOT NULL DEFAULT '',
            enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            created_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_skills_tenant_name ON skills(tenant_id, name)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skills")
