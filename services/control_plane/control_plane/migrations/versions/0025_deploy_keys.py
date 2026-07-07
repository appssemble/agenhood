"""skill deploy keys: deploy_keys table + skills.deploy_key_id

Revision ID: 0025_deploy_keys
Revises: 0024_container_resource_limits
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op

revision = "0025_deploy_keys"
down_revision = "0024_container_resource_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE deploy_keys (
            id                          TEXT PRIMARY KEY,
            tenant_id                   TEXT NOT NULL REFERENCES tenants(id),
            name                        TEXT NOT NULL,
            ssh_private_key_ciphertext  BYTEA NOT NULL,
            ssh_public_key              TEXT NOT NULL,
            key_type                    TEXT NOT NULL,
            key_fingerprint             TEXT NOT NULL,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_deploy_keys_tenant_name ON deploy_keys(tenant_id, name)"
    )
    op.execute(
        "ALTER TABLE skills ADD COLUMN deploy_key_id TEXT REFERENCES deploy_keys(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE skills DROP COLUMN IF EXISTS deploy_key_id")
    op.execute("DROP TABLE IF EXISTS deploy_keys")
