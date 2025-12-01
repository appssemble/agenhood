"""chatgpt subscription auth: oauth credential columns + oauth_connections

Revision ID: 0005_chatgpt_subscription_auth
Revises: 0004_unit4_lifecycle_columns
Create Date: 2026-06-04
"""
from __future__ import annotations

from alembic import op

revision = "0005_chatgpt_subscription_auth"
down_revision = "0004_unit4_lifecycle_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- credentials: add oauth columns; relax api-key columns to nullable ---
    op.execute(
        "ALTER TABLE credentials "
        "ADD COLUMN IF NOT EXISTS auth_method TEXT NOT NULL DEFAULT 'api_key'"
    )
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS access_token_ciphertext BYTEA")
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS refresh_token_ciphertext BYTEA")
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ")
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS oauth_metadata JSONB")
    op.execute(
        "ALTER TABLE credentials "
        "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'"
    )
    op.execute("ALTER TABLE credentials ALTER COLUMN key_ciphertext DROP NOT NULL")
    op.execute("ALTER TABLE credentials ALTER COLUMN key_last4 DROP NOT NULL")

    # Swap the unique index to include auth_method so api_key + oauth coexist.
    op.execute("DROP INDEX IF EXISTS idx_credentials_tenant_provider")
    op.execute(
        "CREATE UNIQUE INDEX idx_credentials_tenant_provider_method "
        "ON credentials(tenant_id, provider, auth_method)"
    )

    # --- oauth_connections: short-lived device-flow state ---
    op.execute(
        """
        CREATE TABLE oauth_connections (
            id                      TEXT PRIMARY KEY,
            tenant_id               TEXT NOT NULL REFERENCES tenants(id),
            provider                TEXT NOT NULL,
            device_code_ciphertext  BYTEA NOT NULL,
            status                  TEXT NOT NULL DEFAULT 'pending',
            error                   TEXT,
            credential_id           TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at              TIMESTAMPTZ NOT NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_oauth_connections_sweep "
        "ON oauth_connections(status, expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_connections")
    op.execute("DROP INDEX IF EXISTS idx_credentials_tenant_provider_method")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_tenant_provider "
        "ON credentials(tenant_id, provider)"
    )
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS oauth_metadata")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS token_expires_at")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS refresh_token_ciphertext")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS access_token_ciphertext")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS auth_method")
    # key_ciphertext/key_last4 NOT NULL is intentionally NOT restored on downgrade
    # (oauth rows may have left them NULL).
