"""unit3: extend tenants, users, sessions, api_keys, credentials

Revision ID: 0003_unit3_tenancy_auth
Revises: 0001_unit2_core_tables
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision = "0003_unit3_tenancy_auth"
down_revision = "0001_unit2_core_tables"  # Unit 2's head (confirmed with alembic heads)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unit 2 created tenants(id, name, limits, status, created_at) so templates,
    # containers, tasks and events can FK to it. Unit 3 owns the real tenancy
    # feature and only adds the columns Unit 2 intentionally omitted.
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS"
        " updated_at TIMESTAMPTZ NOT NULL DEFAULT now();"
    )
    op.execute("""
        CREATE TABLE users (
            id              TEXT PRIMARY KEY,
            tenant_id       TEXT REFERENCES tenants(id),
            email           TEXT NOT NULL UNIQUE,
            name            TEXT NOT NULL,
            password_hash   TEXT NOT NULL,
            role            TEXT NOT NULL,
            is_staff        BOOLEAN NOT NULL DEFAULT false,
            must_change_password BOOLEAN NOT NULL DEFAULT false,
            status          TEXT NOT NULL DEFAULT 'active',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT staff_has_no_tenant CHECK ((is_staff) = (tenant_id IS NULL))
        );
    """)
    op.execute("CREATE INDEX idx_users_tenant ON users(tenant_id);")
    op.execute("""
        CREATE UNIQUE INDEX idx_users_one_owner ON users(tenant_id)
            WHERE role = 'owner' AND status = 'active';
    """)
    op.execute("""
        CREATE TABLE sessions (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash      TEXT NOT NULL UNIQUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at      TIMESTAMPTZ NOT NULL,
            revoked_at      TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX idx_sessions_user ON sessions(user_id);")
    op.execute("CREATE INDEX idx_sessions_expiry ON sessions(expires_at);")
    op.execute("""
        CREATE TABLE api_keys (
            id              TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL REFERENCES tenants(id),
            name            TEXT NOT NULL,
            key_hash        TEXT NOT NULL UNIQUE,
            key_prefix      TEXT NOT NULL,
            created_by      TEXT REFERENCES users(id),
            last_used_at    TIMESTAMPTZ,
            status          TEXT NOT NULL DEFAULT 'active',
            revoked_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX idx_api_keys_tenant ON api_keys(tenant_id);")
    op.execute("""
        CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix) WHERE status = 'active';
    """)
    op.execute("""
        CREATE TABLE credentials (
            id              TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL REFERENCES tenants(id),
            provider        TEXT NOT NULL,
            key_ciphertext  BYTEA NOT NULL,
            key_last4       TEXT NOT NULL,
            created_by      TEXT REFERENCES users(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX idx_credentials_tenant_provider
            ON credentials(tenant_id, provider);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS credentials;")
    op.execute("DROP TABLE IF EXISTS api_keys;")
    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS updated_at;")
