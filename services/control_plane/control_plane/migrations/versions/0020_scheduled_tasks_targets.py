"""scheduled_tasks rework: tenant-scoped with a polymorphic target + backfill

Moves scheduled_tasks from container-scoped (inline driver/model/task_body) to
tenant-scoped with a polymorphic ``target`` JSONB. Each existing inline row is
backfilled by auto-creating a ``prompts`` row from ``task_body->>'prompt'`` and
pointing ``target`` at it (kind='prompt').

Revision ID: 0020_scheduled_tasks_targets
Revises: 0019_workflows
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0020_scheduled_tasks_targets"
down_revision = "0019_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the new polymorphic target column (nullable for now; backfilled below).
    op.execute("ALTER TABLE scheduled_tasks ADD COLUMN target JSONB")
    # 2. Rename last_task_id -> last_run_ref.
    op.execute("ALTER TABLE scheduled_tasks RENAME COLUMN last_task_id TO last_run_ref")
    # 3. The old container-scoped index references container_id, which is dropped below.
    op.execute("DROP INDEX IF EXISTS idx_scheduled_tasks_container")
    # 4. Backfill: for each existing schedule, auto-create a prompt from its inline
    #    task_body and point target at it. The prompt name embeds the schedule id so
    #    it cannot collide on the (tenant_id, name) unique index (idx_prompts_tenant_name).
    #    gen_random_uuid() is built into Postgres 16.
    op.execute(
        """
        DO $$
        DECLARE
            st RECORD;
            new_pid TEXT;
        BEGIN
            FOR st IN SELECT * FROM scheduled_tasks LOOP
                new_pid := 'prm_' || lower(replace(gen_random_uuid()::text, '-', ''));
                INSERT INTO prompts (id, tenant_id, name, body, tags, variables)
                VALUES (
                    new_pid,
                    st.tenant_id,
                    '(migrated) ' || st.name || ' [' || st.id || ']',
                    coalesce(st.task_body->>'prompt', ''),
                    '[]'::jsonb,
                    '[]'::jsonb
                );
                UPDATE scheduled_tasks
                SET target = jsonb_build_object(
                    'kind', 'prompt',
                    'container_id', st.container_id,
                    'prompt_id', new_pid,
                    'variables', '{}'::jsonb
                )
                WHERE id = st.id;
            END LOOP;
        END $$;
        """
    )
    # 5. Now that every row has a target, enforce NOT NULL.
    op.execute("ALTER TABLE scheduled_tasks ALTER COLUMN target SET NOT NULL")
    # 6. Drop the obsolete container-scoped columns.
    op.execute(
        "ALTER TABLE scheduled_tasks "
        "DROP COLUMN task_body, "
        "DROP COLUMN driver, "
        "DROP COLUMN model, "
        "DROP COLUMN container_id"
    )


def downgrade() -> None:
    # Best-effort reverse. The auto-created prompts from the backfill are LEFT in
    # place — we cannot reliably tell which prompts were synthesised vs. authored.
    op.execute("ALTER TABLE scheduled_tasks ADD COLUMN task_body JSONB")
    op.execute("ALTER TABLE scheduled_tasks ADD COLUMN driver TEXT")
    op.execute("ALTER TABLE scheduled_tasks ADD COLUMN model TEXT")
    op.execute("ALTER TABLE scheduled_tasks ADD COLUMN container_id TEXT")
    op.execute("ALTER TABLE scheduled_tasks DROP COLUMN target")
    op.execute("ALTER TABLE scheduled_tasks RENAME COLUMN last_run_ref TO last_task_id")
    op.execute(
        "CREATE INDEX idx_scheduled_tasks_container "
        "ON scheduled_tasks (container_id, created_at DESC)"
    )
