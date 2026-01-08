"""third-party skills: git source + cached bundle columns

Revision ID: 0009_skill_sources
Revises: 0008_template_skills
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op

revision = "0009_skill_sources"
down_revision = "0008_template_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE skills
            ADD COLUMN source_type    TEXT    NOT NULL DEFAULT 'inline',
            ADD COLUMN source_url      TEXT,
            ADD COLUMN source_subpath  TEXT,
            ADD COLUMN source_ref      TEXT,
            ADD COLUMN pinned_sha      TEXT,
            ADD COLUMN bundle          BYTEA,
            ADD COLUMN bundle_sha256   TEXT,
            ADD COLUMN bundle_size     INTEGER
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE skills
            DROP COLUMN source_type,
            DROP COLUMN source_url,
            DROP COLUMN source_subpath,
            DROP COLUMN source_ref,
            DROP COLUMN pinned_sha,
            DROP COLUMN bundle,
            DROP COLUMN bundle_sha256,
            DROP COLUMN bundle_size
        """
    )
