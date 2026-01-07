"""templates redesign: skills column on templates

Revision ID: 0008_template_skills
Revises: 0007_skills
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op

revision = "0008_template_skills"
down_revision = "0007_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE templates ADD COLUMN skills JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS skills")
