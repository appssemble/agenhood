"""templates.effort: optional reasoning-effort seed for containers

Revision ID: 0027_template_effort
Revises: 0026_template_resources
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

revision = "0027_template_effort"
down_revision = "0026_template_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL = "not set", the CLI/model default applies.
    op.execute("ALTER TABLE templates ADD COLUMN effort TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS effort")
