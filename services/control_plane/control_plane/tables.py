from __future__ import annotations

import sqlalchemy as sa

# Reuse Unit 2's MetaData so all tables share one registry.
from control_plane.models_db import metadata  # Unit 2 exposes `metadata`

tenants = sa.Table(
    "tenants", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("limits", sa.JSON, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True)),
    extend_existing=True,
)

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("email", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("is_staff", sa.Boolean, nullable=False),
    sa.Column("must_change_password", sa.Boolean, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True)),
    extend_existing=True,
)

memberships = sa.Table(
    "memberships", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
    sa.Column("role", sa.Text, nullable=False),            # owner | admin | member
    sa.Column("status", sa.Text, nullable=False, server_default="active"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True)),
    sa.UniqueConstraint("user_id", "tenant_id", name="uq_membership"),
    extend_existing=True,
)
sa.Index("idx_memberships_user", memberships.c.user_id)
sa.Index("idx_memberships_tenant", memberships.c.tenant_id)
sa.Index(
    "idx_membership_one_owner", memberships.c.tenant_id,
    unique=True, postgresql_where=sa.text("role = 'owner' AND status = 'active'"),
)


sessions = sa.Table(
    "sessions", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("user_id", sa.Text, nullable=False),
    sa.Column("active_tenant_id", sa.Text),
    sa.Column("token_hash", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
    extend_existing=True,
)

api_keys = sa.Table(
    "api_keys", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("key_hash", sa.Text, nullable=False),
    sa.Column("key_prefix", sa.Text, nullable=False),
    sa.Column("created_by", sa.Text),
    sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    extend_existing=True,
)

credentials = sa.Table(
    "credentials", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("key_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("key_last4", sa.Text, nullable=True),
    sa.Column("auth_method", sa.Text, nullable=False, server_default="api_key"),
    sa.Column("access_token_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("refresh_token_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("oauth_metadata", sa.JSON, nullable=True),
    sa.Column("status", sa.Text, nullable=False, server_default="active"),
    sa.Column("created_by", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True)),
    extend_existing=True,
)

oauth_connections = sa.Table(
    "oauth_connections", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("device_code_ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="pending"),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("credential_id", sa.Text, nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True),
        nullable=False, server_default=sa.text("now()"),
    ),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    extend_existing=True,
)
