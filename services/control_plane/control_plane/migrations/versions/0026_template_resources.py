"""template runtime resources: image_variant + mem_limit + cpus per template

Revision ID: 0026_template_resources
Revises: 0025_deploy_keys
Create Date: 2026-07-08
"""
from __future__ import annotations

from alembic import op

revision = "0026_template_resources"
down_revision = "0025_deploy_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL = "not set", containers fall through to variant defaults.
    op.execute("ALTER TABLE templates ADD COLUMN image_variant TEXT")
    op.execute("ALTER TABLE templates ADD COLUMN mem_limit TEXT")
    op.execute("ALTER TABLE templates ADD COLUMN cpus DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS cpus")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS mem_limit")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS image_variant")
