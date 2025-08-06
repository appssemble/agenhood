"""unit2 core tables: tenants(min), templates, containers, tasks, events

Revision ID: 0001_unit2_core_tables
Revises:
Create Date: 2026-05-20
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_unit2_core_tables"
down_revision = None
branch_labels = None
depends_on = None

_NOW = sa.text("now()")
_TS = sa.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("limits", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("driver", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "system_prompt_mode", sa.Text(), nullable=False,
            server_default=sa.text("'augment'"),
        ),
        sa.Column("tools", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("limits", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("(is_builtin) = (tenant_id IS NULL)", name="builtin_has_no_tenant"),
    )
    op.create_index("idx_templates_tenant", "templates", ["tenant_id"])
    op.create_index(
        "idx_templates_builtin_driver", "templates", ["driver"],
        unique=True, postgresql_where=sa.text("is_builtin = true"),
    )

    op.create_table(
        "containers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("docker_name", sa.Text(), nullable=False),
        sa.Column("volume_name", sa.Text(), nullable=False),
        sa.Column("shim_token", sa.Text(), nullable=False),
        sa.Column("image_tag", sa.Text(), nullable=False),
        sa.Column(
            "image_variant", sa.Text(), nullable=False, server_default=sa.text("'full'"),
        ),
        sa.Column("template_id", sa.Text(), sa.ForeignKey("templates.id"), nullable=True),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("resources", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_task_at", _TS, nullable=True),
        sa.Column(
            "recovery_attempts", sa.Integer(), nullable=False, server_default=sa.text("0"),
        ),
        sa.Column("destroy_delete_volume", sa.Boolean(), nullable=True),
        sa.Column("status_changed_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("docker_name", name="uq_containers_docker_name"),
        sa.UniqueConstraint("volume_name", name="uq_containers_volume_name"),
    )
    op.create_index("idx_containers_tenant", "containers", ["tenant_id"])
    op.create_index("idx_containers_status", "containers", ["status"])
    op.create_index(
        "idx_containers_idle", "containers", ["status", "last_task_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "idx_containers_external", "containers", ["tenant_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND status <> 'destroyed'"),
    )
    op.create_index(
        "idx_containers_dormant", "containers", ["status", "status_changed_at"],
        postgresql_where=sa.text("status IN ('paused','archived')"),
    )
    op.create_index(
        "idx_containers_transient", "containers", ["status", "status_changed_at"],
        postgresql_where=sa.text(
            "status IN ('provisioning','resuming','pausing','archiving','recovering','destroying')"
        ),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("container_id", sa.Text(), sa.ForeignKey("containers.id"), nullable=False),
        sa.Column("driver", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("body", JSONB(), nullable=False),
        sa.Column("config_snapshot", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("iterations_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_in", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_out", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("ended_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index(
        "idx_tasks_container", "tasks", ["container_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_tasks_tenant", "tasks", ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_tasks_status", "tasks", ["status"],
        postgresql_where=sa.text("status IN ('pending','running')"),
    )

    op.create_table(
        "events",
        sa.Column(
            "task_id", sa.Text(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("ts", _TS, nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("task_id", "seq"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("ts", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index("idx_audit_ts", "audit_log", [sa.text("ts DESC")])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("events")
    op.drop_table("tasks")
    op.drop_table("containers")
    op.drop_table("templates")
    op.drop_table("tenants")
