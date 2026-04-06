"""prompts: tenant-shared reusable prompt library

Revision ID: 0017_prompts
Revises: 0016_mcp_servers
Create Date: 2026-06-24
"""
from __future__ import annotations

from alembic import op

revision = "0017_prompts"
down_revision = "0016_mcp_servers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE prompts (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            name        TEXT NOT NULL,
            body        TEXT NOT NULL,
            tags        JSONB NOT NULL DEFAULT '[]'::jsonb,
            variables   JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_prompts_tenant_name ON prompts(tenant_id, name)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompts")
