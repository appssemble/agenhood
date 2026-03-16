"""mcp servers: mcp_servers table + templates.mcp_servers column

Revision ID: 0016_mcp_servers
Revises: 0015_linked_repos
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op

revision = "0016_mcp_servers"
down_revision = "0015_linked_repos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mcp_servers (
            id                TEXT PRIMARY KEY,
            tenant_id         TEXT NOT NULL REFERENCES tenants(id),
            name              TEXT NOT NULL,
            description       TEXT NOT NULL DEFAULT '',
            url               TEXT NOT NULL,
            auth_type         TEXT NOT NULL DEFAULT 'none',
            auth_header_name  TEXT,
            secret_ciphertext BYTEA,
            enabled           BOOLEAN NOT NULL DEFAULT TRUE,
            created_by        TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_mcp_servers_tenant_name ON mcp_servers(tenant_id, name)"
    )
    op.execute(
        "ALTER TABLE templates ADD COLUMN mcp_servers JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS mcp_servers")
    op.execute("DROP TABLE IF EXISTS mcp_servers")
