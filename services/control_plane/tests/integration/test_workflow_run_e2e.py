"""Integration test: 2-step workflow run walks cursor 0→1→completed against a real DB.

Uses the ``migrated_db`` fixture (testcontainers Postgres only — no agent image or
stub LLM required).  Only ``submit_step`` and ``_task_status`` are faked; all DB
writes go to the real Postgres so this proves the engine's row-locking, cursor-
advance, and FK bookkeeping end-to-end.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker",
    ),
]


@pytest.mark.asyncio
async def test_two_step_run_completes(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drives advance_workflow_runs against a real DB with a fake task-status source.

    The submit + task-status layer is monkeypatched; the DB is real (migrated_db's
    testcontainer Postgres).  Proves the run reaches status='completed', cursor=1
    after two advance ticks.
    """
    import control_plane.workflow_engine as eng
    from control_plane.ids import new_container_id, new_prompt_id, new_workflow_id
    from control_plane.models_db import (
        containers,
        prompts,
        tasks,
        tenants,
        workflow_runs,
        workflows,
    )

    engine = create_async_engine(migrated_db)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Use a fresh tenant ID per test invocation so the session-scoped Postgres
    # container shared across the integration suite never sees a duplicate.
    _sfx = uuid.uuid4().hex[:8]
    TENANT_ID = f"ten-wfe2e-{_sfx}"

    cid = new_container_id()
    pid_a = new_prompt_id()
    pid_b = new_prompt_id()
    wf_id = new_workflow_id()

    # ------------------------------------------------------------------
    # Seed: tenant → container → two prompts → 2-step workflow
    # ------------------------------------------------------------------
    async with factory() as s:
        await s.execute(sa.insert(tenants).values(id=TENANT_ID, name="WF E2E Test"))
        await s.execute(
            sa.insert(containers).values(
                id=cid,
                tenant_id=TENANT_ID,
                name="wfe2e-con",
                docker_name=f"agent-c-wfe2e-{cid[4:12]}",
                volume_name=f"agent-vol-wfe2e-{cid[4:12]}",
                shim_token="tok_wfe2e",
                image_tag="test",
                config={"driver": "vanilla"},
                status="running",
            )
        )
        await s.execute(
            sa.insert(prompts).values(
                id=pid_a, tenant_id=TENANT_ID, name="Prompt A", body="Do step A",
            )
        )
        await s.execute(
            sa.insert(prompts).values(
                id=pid_b, tenant_id=TENANT_ID, name="Prompt B", body="Do step B",
            )
        )
        steps = [
            {"prompt_id": pid_a, "container_id": cid, "variables": {}},
            {"prompt_id": pid_b, "container_id": cid, "variables": {}},
        ]
        await s.execute(
            sa.insert(workflows).values(
                id=wf_id,
                tenant_id=TENANT_ID,
                name="E2E Workflow",
                steps=steps,
            )
        )
        await s.commit()

    # ------------------------------------------------------------------
    # Fake submit_step: inserts a minimal tasks row and returns its ID.
    # The FK workflow_runs.current_task_id → tasks.id requires a real row.
    # ------------------------------------------------------------------
    _task_ids = iter([f"tsk-wfe2e-a-{_sfx}", f"tsk-wfe2e-b-{_sfx}"])

    async def _fake_submit_step(
        session: Any,
        *,
        step: dict[str, Any],
        step_index: int,
        workflow_id: str,
        run_id: str,
        tenant_id: str,
        **kw: Any,
    ) -> str:
        tid = next(_task_ids)
        await session.execute(
            sa.insert(tasks).values(
                id=tid,
                tenant_id=tenant_id,
                container_id=step["container_id"],
                driver="vanilla",
                body={"prompt": "fake"},
                config_snapshot={},
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        return tid

    # Fake _task_status: always reports the current step as "completed".
    # Returns (status, resolved_timeout_seconds) to match the real helper.
    async def _fake_task_status(
        db: Any, task_id: str | None
    ) -> tuple[str | None, int | None]:
        if task_id is None:
            return None, None
        return "completed", None

    monkeypatch.setattr(eng, "submit_step", _fake_submit_step)
    monkeypatch.setattr(eng, "_task_status", _fake_task_status)

    # settings is only passed through to submit_step (which we've faked), so a
    # sentinel object is enough.
    _settings = object()
    wf_dict: dict[str, Any] = {"id": wf_id, "steps": steps}

    # ------------------------------------------------------------------
    # start_run: submits step 0 (via fake), inserts workflow_run at cursor=0
    # ------------------------------------------------------------------
    async with factory() as s:
        run_id = await eng.start_run(
            s,
            settings=_settings,
            session_factory=factory,
            docker_client=None,
            shim_dispatcher=None,
            tenant_id=TENANT_ID,
            workflow=wf_dict,
            trigger_source="manual",
        )

    # ------------------------------------------------------------------
    # Advance tick 1: step 0 "completed" → cursor 0→1, submit step 1
    # ------------------------------------------------------------------
    async with factory() as s:
        await eng.advance_workflow_runs(
            s,
            None,
            None,
            settings=_settings,
            session_factory=factory,
        )

    # ------------------------------------------------------------------
    # Advance tick 2: step 1 "completed" at cursor==step_count-1 → completed
    # ------------------------------------------------------------------
    async with factory() as s:
        await eng.advance_workflow_runs(
            s,
            None,
            None,
            settings=_settings,
            session_factory=factory,
        )

    # ------------------------------------------------------------------
    # Assert final state in the DB
    # ------------------------------------------------------------------
    async with factory() as s:
        row = (
            await s.execute(
                sa.select(workflow_runs).where(workflow_runs.c.id == run_id)
            )
        ).mappings().first()

    assert row is not None, f"workflow_runs row {run_id!r} not found"
    assert row["status"] == "completed", (
        f"expected status='completed', got {row['status']!r}"
    )
    assert row["cursor"] == 1, f"expected cursor=1, got {row['cursor']!r}"

    await engine.dispose()
