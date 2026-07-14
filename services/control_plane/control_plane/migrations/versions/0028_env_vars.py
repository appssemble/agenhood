"""env_vars: per-container / per-template environment variables

Revision ID: 0028_env_vars
Revises: 0027_template_effort
Create Date: 2026-07-14
"""
from __future__ import annotations

from alembic import op

revision = "0028_env_vars"
down_revision = "0027_template_effort"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL = "no env vars". Items are {"name","value","secret"} or
    # {"name","secret":true,"ciphertext"} (AES-GCM, base64) — see env_vars.py.
    op.execute("ALTER TABLE containers ADD COLUMN env_vars JSONB")
    op.execute("ALTER TABLE templates ADD COLUMN env_vars JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS env_vars")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS env_vars")
