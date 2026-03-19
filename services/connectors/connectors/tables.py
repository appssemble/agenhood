from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()  # connectors' OWN registry — not control_plane's

connections = sa.Table(
    "connections", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("external_id", sa.Text, nullable=False),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("access_token_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("refresh_token_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("cp_api_key_ciphertext", sa.LargeBinary, nullable=True),
    sa.Column("scopes", sa.Text, nullable=False, server_default=""),
    sa.Column("connection_metadata", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.UniqueConstraint("tenant_id", "provider", "external_id", name="uq_conn_identity"),
)

container_bindings = sa.Table(
    "container_bindings", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("connection_id", sa.Text, sa.ForeignKey("connections.id"), nullable=False),
    sa.Column("container_id", sa.Text, nullable=False),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("resource_filters", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

routing_rules = sa.Table(
    "routing_rules", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("connection_id", sa.Text, sa.ForeignKey("connections.id"), nullable=False),
    sa.Column("tenant_id", sa.Text, nullable=False),
    sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
    sa.Column("match", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("target", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("input_template", sa.Text, nullable=False, server_default="{{ text }}"),
    sa.Column("surface", sa.JSON, nullable=False, server_default='["reasoning","result"]'),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

deliveries = sa.Table(
    "deliveries", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("task_id", sa.Text, nullable=False, unique=True),
    sa.Column("container_id", sa.Text, nullable=False),
    sa.Column("connection_id", sa.Text, sa.ForeignKey("connections.id"), nullable=False),
    sa.Column("origin_ref", sa.JSON, nullable=False),
    sa.Column("provider_message_handle", sa.JSON, nullable=True),
    sa.Column("surface", sa.JSON, nullable=False, server_default='["reasoning","result"]'),
    sa.Column("last_seq", sa.Integer, nullable=False, server_default="0"),
    sa.Column("state", sa.Text, nullable=False, server_default="streaming"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

webhook_events = sa.Table(
    "webhook_events", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("external_delivery_id", sa.Text, nullable=False),
    sa.Column("payload_digest", sa.Text, nullable=False),
    sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("result", sa.Text, nullable=True),
    sa.UniqueConstraint("provider", "external_delivery_id", name="uq_webhook_delivery"),
)

action_log = sa.Table(
    "action_log", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("delivery_id", sa.Text, nullable=True),
    sa.Column("connection_id", sa.Text, nullable=True),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("ok", sa.Boolean, nullable=False),
    sa.Column("detail", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

sa.Index("ix_conn_tenant_provider", connections.c.tenant_id, connections.c.provider)
sa.Index("ix_binding_container", container_bindings.c.container_id)
sa.Index("ix_rule_conn_enabled", routing_rules.c.connection_id,
         routing_rules.c.enabled, routing_rules.c.priority)
