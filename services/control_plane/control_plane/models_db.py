from __future__ import annotations

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

# Minimal tenants table (Unit 3 owns the full feature; FKs need it to exist).
tenants = Table(
    "tenants", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("limits", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

templates = Table(
    "templates", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=True),
    Column("name", Text, nullable=False),
    Column("driver", Text, nullable=False),
    Column("model", Text, nullable=True),
    Column("system_prompt", Text, nullable=False, server_default=text("''")),
    Column("system_prompt_mode", Text, nullable=False, server_default=text("'augment'")),
    Column("tools", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("skills", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("mcp_servers", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("limits", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("is_builtin", Boolean, nullable=False, server_default=text("false")),
    Column("created_by", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("(is_builtin) = (tenant_id IS NULL)", name="builtin_has_no_tenant"),
)
Index("idx_templates_tenant", templates.c.tenant_id)
Index(
    "idx_templates_builtin_driver", templates.c.driver,
    unique=True, postgresql_where=text("is_builtin = true"),
)

containers = Table(
    "containers", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("external_id", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("docker_name", Text, nullable=False, unique=True),
    Column("volume_name", Text, nullable=False, unique=True),
    Column("shim_token", Text, nullable=False),
    Column("image_tag", Text, nullable=False),
    Column("image_variant", Text, nullable=False, server_default=text("'full'")),
    Column("template_id", Text, ForeignKey("templates.id"), nullable=True),
    Column("config", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("resources", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("last_task_at", TIMESTAMP(timezone=True), nullable=True),
    Column("recovery_attempts", Integer, nullable=False, server_default=text("0")),
    Column("git_mode", Text, nullable=False, server_default=text("'snapshot'")),
    Column("destroy_delete_volume", Boolean, nullable=True),
    Column(
        "status_changed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    ),
    Column("error_message", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_containers_tenant", containers.c.tenant_id)
Index("idx_containers_status", containers.c.status)
Index(
    "idx_containers_idle", containers.c.status, containers.c.last_task_at,
    postgresql_where=text("status = 'running'"),
)
Index(
    "idx_containers_external", containers.c.tenant_id, containers.c.external_id,
    unique=True, postgresql_where=text("external_id IS NOT NULL AND status <> 'destroyed'"),
)
Index(
    "idx_containers_dormant", containers.c.status, containers.c.status_changed_at,
    postgresql_where=text("status IN ('paused','archived')"),
)
Index(
    "idx_containers_transient", containers.c.status, containers.c.status_changed_at,
    postgresql_where=text(
        "status IN ('provisioning','resuming','pausing','archiving','recovering','destroying')"
    ),
)

tasks = Table(
    "tasks", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("container_id", Text, ForeignKey("containers.id"), nullable=False),
    Column(
        "scheduled_task_id", Text,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), nullable=True,
    ),
    Column("session_id", Text, nullable=True),
    Column("driver", Text, nullable=False),
    Column("model", Text, nullable=True),
    Column("body", JSONB, nullable=False),
    Column("config_snapshot", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("result", JSONB, nullable=True),
    Column("error_code", Text, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("iterations_used", Integer, nullable=False, server_default=text("0")),
    Column("tokens_in", BigInteger, nullable=False, server_default=text("0")),
    Column("tokens_out", BigInteger, nullable=False, server_default=text("0")),
    Column("started_at", TIMESTAMP(timezone=True), nullable=True),
    Column("ended_at", TIMESTAMP(timezone=True), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_tasks_container", tasks.c.container_id, tasks.c.created_at.desc())
Index("idx_tasks_tenant", tasks.c.tenant_id, tasks.c.created_at.desc())
Index(
    "idx_tasks_status", tasks.c.status,
    postgresql_where=text("status IN ('pending','running')"),
)
Index("idx_tasks_scheduled", tasks.c.scheduled_task_id)
Index("idx_tasks_session", tasks.c.session_id)

scheduled_tasks = Table(
    "scheduled_tasks", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    # Polymorphic target (migration 0020): {"kind": "prompt"|..., ...}. Replaces
    # the old container-scoped driver/model/task_body columns.
    Column("target", JSONB, nullable=False),
    Column("schedule", JSONB, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("next_run_at", TIMESTAMP(timezone=True), nullable=True),
    Column("last_run_at", TIMESTAMP(timezone=True), nullable=True),
    Column("last_run_ref", Text, nullable=True),
    Column("last_status", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index(
    "idx_scheduled_tasks_due", scheduled_tasks.c.next_run_at,
    postgresql_where=text("enabled AND next_run_at IS NOT NULL"),
)

events = Table(
    "events", metadata,
    Column("task_id", Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
events.append_constraint(
    PrimaryKeyConstraint("task_id", "seq")
)

# Workspace git remotes (workspace git rollback spec): one optional push-only
# remote per container. Token is AES-GCM ciphertext; never stored plaintext.
git_remotes = Table(
    "git_remotes", metadata,
    Column(
        "container_id", Text,
        ForeignKey("containers.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column("url", Text, nullable=False),
    Column("branch", Text, nullable=False, server_default=text("'main'")),
    Column("ssh_private_key_ciphertext", LargeBinary, nullable=True),
    Column("ssh_public_key", Text, nullable=True),
    Column("key_type", Text, nullable=True),
    Column("key_fingerprint", Text, nullable=True),
    Column("verified_at", TIMESTAMP(timezone=True), nullable=True),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("last_push_status", Text, nullable=True),   # 'pushed' | 'failed'
    Column("last_push_error", Text, nullable=True),
    Column("last_push_at", TIMESTAMP(timezone=True), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

# Linked repo (pull mode): the workspace is a one-time clone of an external
# branch. Holds a SEPARATE read-scoped deploy key from git_remotes; presence of
# this row does not by itself mean "linked" — containers.git_mode is the switch.
linked_repos = Table(
    "linked_repos", metadata,
    Column(
        "container_id", Text,
        ForeignKey("containers.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column("url", Text, nullable=False, server_default=text("''")),
    Column("branch", Text, nullable=False, server_default=text("'main'")),
    Column("ssh_private_key_ciphertext", LargeBinary, nullable=True),
    Column("ssh_public_key", Text, nullable=True),
    Column("key_type", Text, nullable=True),
    Column("key_fingerprint", Text, nullable=True),
    Column("verified_at", TIMESTAMP(timezone=True), nullable=True),
    Column("linked_at", TIMESTAMP(timezone=True), nullable=True),
    Column("last_clone_status", Text, nullable=True),   # 'cloned' | 'failed'
    Column("last_clone_error", Text, nullable=True),
    Column("last_clone_at", TIMESTAMP(timezone=True), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

# Opencode Agent Skills (spec: opencode skills): tenant-scoped library. The body
# is the markdown shown to the model; (tenant_id, name) is unique.
skills = Table(
    "skills", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("body", Text, nullable=False, server_default=text("''")),
    Column("source_type", Text, nullable=False, server_default=text("'inline'")),
    Column("source_url", Text, nullable=True),
    Column("source_subpath", Text, nullable=True),
    Column("source_ref", Text, nullable=True),
    Column("pinned_sha", Text, nullable=True),
    Column("bundle", LargeBinary, nullable=True),
    Column("bundle_sha256", Text, nullable=True),
    Column("bundle_size", Integer, nullable=True),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("created_by", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_skills_tenant_name", skills.c.tenant_id, skills.c.name, unique=True)

mcp_servers = Table(
    "mcp_servers", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("url", Text, nullable=False),
    Column("auth_type", Text, nullable=False, server_default=text("'none'")),
    Column("auth_header_name", Text, nullable=True),
    Column("secret_ciphertext", LargeBinary, nullable=True),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("created_by", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

prompts = Table(
    "prompts", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("tags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("variables", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_by", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_prompts_tenant_name", prompts.c.tenant_id, prompts.c.name, unique=True)

workflows = Table(
    "workflows", metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("steps", JSONB, nullable=False),
    Column("created_by", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_workflows_tenant_name", workflows.c.tenant_id, workflows.c.name, unique=True)

workflow_runs = Table(
    "workflow_runs", metadata,
    Column("id", Text, primary_key=True),
    Column("workflow_id", Text, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("cursor", Integer, nullable=False, server_default=text("0")),
    Column("current_task_id", Text, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
    Column("step_count", Integer, nullable=False),
    Column("error_step", Integer, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("trigger_source", Text, nullable=False),
    Column(
        "scheduled_task_id", Text,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), nullable=True,
    ),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("step_started_at", TIMESTAMP(timezone=True), nullable=True),
    Column("ended_at", TIMESTAMP(timezone=True), nullable=True),
    Column("steps", JSONB, nullable=True),
)
Index("idx_wfr_active", workflow_runs.c.workflow_id, postgresql_where=text("status = 'running'"))
Index(
    "idx_wfr_schedule", workflow_runs.c.scheduled_task_id,
    postgresql_where=text("scheduled_task_id IS NOT NULL AND status = 'running'"),
)
Index("idx_wfr_history", workflow_runs.c.workflow_id, workflow_runs.c.started_at.desc())

workflow_events = Table(
    "workflow_events", metadata,
    Column("run_id", Text, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("type", Text, nullable=False),       # started | step_advanced | completed | failed
    Column("payload", JSONB, nullable=False),
    Column("ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
workflow_events.append_constraint(
    PrimaryKeyConstraint("run_id", "seq")
)

# Append-only audit of admin actions and significant lifecycle events (spec §5, §4.1).
# No FKs: actor/target are loose TEXT so rows outlive the things they reference.
audit_log = Table(
    "audit_log", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("actor_type", Text, nullable=False),   # tenant | admin | system
    Column("actor_id", Text, nullable=True),
    Column("action", Text, nullable=False),
    Column("target_type", Text, nullable=True),
    Column("target_id", Text, nullable=True),
    Column("details", JSONB, nullable=True),
    Column("ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
Index("idx_audit_ts", audit_log.c.ts.desc())
