"""Unit D — Task 4: Scheduler + admission gap-fill.

Fills these coverage gaps (scheduler.py at 71%, missing listed lines):

  - `scheduled_target.py`  lines 10, 17, 20, 26  (validate_target error branches)
  - `scheduler.py`         line  125              (prompt not found → failed)
  - `scheduler.py`         line  153              (workflow not found → failed)
  - `scheduler.py`         line  168              (unknown target kind → failed)
  - `scheduler.py`         lines 196-197          (Phase B exception → Phase A still runs)
  - `scheduler.py`         lines 216-233          (claim + fire phase with non-empty due rows)
  - `routers/tasks.py`     lines 373-374          (concurrency cap → 429 too_many_tasks)

No test duplicates existing coverage in:
  - test_scheduled_target.py   (prompt_ok, workflow_ok, bad_kind, missing_container_id)
  - test_scheduler_phase_b.py  (Phase B before Phase A happy-path ordering)
  - test_scheduler_phase_a_targets.py  (prompt/workflow target fire paths)
  - test_task_submit_admission.py  (bring_to_running ordering + error propagation)
  - tests/integration/test_concurrency_cap.py  (shim-side 429 via seeded_app_cap1)
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import control_plane.scheduler as sched
from control_plane.errors import APIError
from control_plane.scheduled_target import validate_target

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers shared across scheduler fire-path tests
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 29, 10, 0, tzinfo=UTC)


class _DueRow:
    def __init__(self, target: dict[str, Any]) -> None:
        self.id = "sch_matrix_1"
        self.tenant_id = "ten_matrix"
        self.schedule = {"kind": "recurring", "unit": "day", "time": "09:00"}
        self.timezone = "UTC"
        self.target = target


async def _fire(row: _DueRow) -> None:
    """Call _submit_due_schedule with sentinel no-op defaults."""
    await sched._submit_due_schedule(
        session=object(),
        row=row,
        now=_NOW,
        settings=object(),
        session_factory=lambda: None,
        docker_client=object(),
        shim_dispatcher=object(),
    )


# ===========================================================================
# Part 1 — validate_target error-branch matrix
# (covers scheduled_target.py lines 10, 17, 20, 26)
# ===========================================================================


@pytest.mark.parametrize(
    "target, expected_kind",
    [
        (
            {"kind": "prompt", "container_id": "con_1", "prompt_id": "pr_1", "variables": {"a": "b"}},  # noqa: E501
            "prompt",
        ),
        (
            {"kind": "workflow", "workflow_id": "wf_1"},
            "workflow",
        ),
    ],
)
def test_validate_target_accepts(target: dict, expected_kind: str) -> None:
    """Valid targets are normalised and returned with the correct kind."""
    out = validate_target(target)
    assert out["kind"] == expected_kind


@pytest.mark.parametrize(
    "bad",
    [
        "not_a_dict",                                                  # line 10: non-dict target
        {"kind": "prompt", "container_id": "", "prompt_id": "pr_1"},   # line 15: empty container_id
        {"kind": "prompt", "container_id": "con_1"},                   # line 17: missing prompt_id
        {
            "kind": "prompt",
            "container_id": "con_1",
            "prompt_id": "pr_1",
            "variables": "bad",
        },                                                              # line 20: non-dict variables  # noqa: E501
        {"kind": "workflow"},                                           # line 26: missing workflow_id  # noqa: E501
        {"kind": "nope"},                                              # line 28: bad kind
    ],
)
def test_validate_target_rejects(bad: Any) -> None:
    """Every invalid target must raise APIError (not a generic exception)."""
    with pytest.raises(APIError):
        validate_target(bad)


# ===========================================================================
# Part 2 — _submit_due_schedule error branches
# (covers scheduler.py lines 125, 153, 168)
# ===========================================================================


@pytest.mark.asyncio
async def test_submit_due_prompt_not_found_records_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If _load_prompt_row returns None, last_status='failed' is recorded (line 125)."""
    row = _DueRow({"kind": "prompt", "prompt_id": "pmt_gone", "container_id": "con_1"})

    async def fake_load_prompt(session: Any, tenant_id: str, prompt_id: str) -> None:
        return None  # prompt deleted since schedule was created

    monkeypatch.setattr(sched, "_load_prompt_row", fake_load_prompt)

    recorded: dict[str, Any] = {}

    async def fake_apply(session: Any, sid: str, values: dict[str, Any]) -> None:
        recorded.update(values)

    monkeypatch.setattr(sched, "_apply_schedule_update", fake_apply)

    await _fire(row)

    assert recorded["last_status"] == "failed"
    assert recorded["last_run_ref"] is None


@pytest.mark.asyncio
async def test_submit_due_workflow_not_found_records_failed(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: E501
    """If _load_workflow_row returns None, last_status='failed' is recorded (line 153)."""
    row = _DueRow({"kind": "workflow", "workflow_id": "wf_gone"})

    async def fake_overlap(session: Any, scheduled_task_id: str) -> bool:
        return False  # no active run, so we proceed to load the workflow

    async def fake_load_workflow(session: Any, tenant_id: str, workflow_id: str) -> None:
        return None  # workflow deleted since schedule was created

    monkeypatch.setattr(sched, "_workflow_overlap_exists", fake_overlap)
    monkeypatch.setattr(sched, "_load_workflow_row", fake_load_workflow)

    recorded: dict[str, Any] = {}

    async def fake_apply(session: Any, sid: str, values: dict[str, Any]) -> None:
        recorded.update(values)

    monkeypatch.setattr(sched, "_apply_schedule_update", fake_apply)

    await _fire(row)

    assert recorded["last_status"] == "failed"
    assert recorded["last_run_ref"] is None


@pytest.mark.asyncio
async def test_submit_due_unknown_kind_records_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown target kind falls to the else-branch (line 168) and records failed."""
    row = _DueRow({"kind": "totally_unknown"})

    recorded: dict[str, Any] = {}

    async def fake_apply(session: Any, sid: str, values: dict[str, Any]) -> None:
        recorded.update(values)

    monkeypatch.setattr(sched, "_apply_schedule_update", fake_apply)

    await _fire(row)

    assert recorded["last_status"] == "failed"
    assert recorded["last_run_ref"] is None


# ===========================================================================
# Part 3 — scheduler_sweep ordering + claim/fire phase
# (covers scheduler.py lines 196-197 and 216-233)
# ===========================================================================


@pytest.mark.asyncio
async def test_phase_b_exception_does_not_abort_phase_a(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase B raises → exception logged (lines 196-197) → Phase A (due query) still executes.

    This is the durable invariant: one bad Phase B must never silently drop
    scheduled-task firings for the entire tick.
    """

    async def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("phase B exploded")

    monkeypatch.setattr(sched, "advance_workflow_runs", boom)

    phase_a_ran: list[str] = []

    class _DB:
        async def execute(self, *a: Any, **k: Any) -> Any:
            class _R:
                def all(self_inner: Any) -> list:
                    phase_a_ran.append("due_query")
                    return []

            return _R()

        async def commit(self) -> None:
            pass

    await sched.scheduler_sweep(
        _DB(), object(), object(),
        settings=object(),
        session_factory=lambda: None,
    )

    assert phase_a_ran, "Phase A (due-schedule query) must run even when Phase B raises"


@pytest.mark.asyncio
async def test_sweep_claims_and_fires_due_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """When due rows exist, the sweep: (a) updates next_run_at per row + single commit
    (claim phase, lines 216-222), then (b) calls _submit_due_schedule for each row
    (fire phase, lines 225-233).

    Phase B is stubbed out so the test is purely about the claim+fire path.
    """

    class _FakeDueRow:
        id = "sch_due_1"
        schedule = {"kind": "once"}  # _advance_values → next_run_at=None, enabled=False
        timezone = "UTC"
        target = {"kind": "prompt", "prompt_id": "pmt_1", "container_id": "con_1"}

    async def fake_advance(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr(sched, "advance_workflow_runs", fake_advance)

    committed: list[bool] = []
    execute_calls: list[int] = []

    class _DB:
        def __init__(self) -> None:
            self._n = 0

        async def execute(self, *a: Any, **k: Any) -> Any:
            self._n += 1
            n = self._n

            class _SelectResult:
                def all(self_inner: Any) -> list:
                    return [_FakeDueRow()]

            class _UpdateResult:
                pass

            execute_calls.append(n)
            return _SelectResult() if n == 1 else _UpdateResult()

        async def commit(self) -> None:
            committed.append(True)

        async def rollback(self) -> None:
            pass

    fired: list[str] = []

    async def fake_submit_due(
        *, session: Any, row: Any, **kwargs: Any
    ) -> None:
        fired.append(row.id)

    monkeypatch.setattr(sched, "_submit_due_schedule", fake_submit_due)

    db = _DB()
    await sched.scheduler_sweep(
        db, object(), object(),
        settings=object(),
        session_factory=lambda: None,
    )

    # Claim phase: at least one execute (select) + one execute (update) + one commit.
    assert len(execute_calls) >= 2, "select + at least one update expected"
    assert committed, "Single claim commit must happen after all updates"

    # Fire phase: _submit_due_schedule called for the one due row.
    assert fired == ["sch_due_1"], (
        f"Fire phase must invoke _submit_due_schedule for each due row; got {fired}"
    )


# ===========================================================================
# Part 4 — Concurrency cap boundary (routers/tasks.py lines 373-374)
# (Decision-tier gap: the control-plane's own inflight count check, distinct
#  from the shim-side 429 covered by tests/integration/test_concurrency_cap.py)
# ===========================================================================


@pytest.mark.asyncio
async def test_submit_task_core_rejects_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control-plane admission gate: when inflight == cap → 429 too_many_tasks.

    Contract asserted:
      - CAP = 4 (default max_concurrent_tasks_per_container)
      - inflight == CAP     → APIError(429, "too_many_tasks")  [N tasks → first rejection]
      - inflight == CAP - 1 → passes cap check (reaches credential lookup; any non-429 exit
                               confirms the cap gate was cleared)

    Monkeypatched at the real seams (_load_owned_container, load_tenant_limits,
    lifecycle.bring_to_running) so the fake session only needs to answer the
    inflight-count query (scalar_one).
    """
    import control_plane.routers.tasks as tasks_mod
    from agentcore.models import TaskBody
    from control_plane.config import Settings

    CAP = 4

    class _FakeRow:
        id = "ctr_cap"
        tenant_id = "ten_cap"
        status = "running"
        docker_name = "agent-cap-test"
        volume_name = "vol-cap"
        image_tag = "latest"
        image_variant = "full"
        shim_token = "tok"
        config: dict[str, Any] = {"driver": "vanilla", "model": "gpt-4o", "tools": []}
        resources: dict[str, Any] = {}
        name = "cap-test"
        external_id = None
        git_mode = "snapshot"
        env_vars = None

    _LIMITS = {
        "max_running_containers": 5,
        "max_concurrent_tasks_per_container": CAP,
        "max_containers": 100,
        "default_max_iterations": 30,
        "default_max_tokens": 200000,
        "default_task_timeout_seconds": 1800,
    }

    async def fake_load_container(session: Any, tid: str, cid: str) -> _FakeRow:
        return _FakeRow()

    async def fake_load_limits(session: Any, tid: str) -> dict[str, Any]:
        return _LIMITS

    async def fake_bring(*a: Any, **k: Any) -> None:
        pass  # admit the container; the cap check is the thing under test

    monkeypatch.setattr(tasks_mod, "_load_owned_container", fake_load_container)
    monkeypatch.setattr(tasks_mod, "load_tenant_limits", fake_load_limits)
    monkeypatch.setattr(tasks_mod.lifecycle, "bring_to_running", fake_bring)

    _settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seed",
        seed_llm_api_key="",
        agent_image_tag="test",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
    )

    # --- N == CAP → rejected ---

    class _AtCapSession:
        async def execute(self, *a: Any, **k: Any) -> Any:
            class _R:
                def scalar_one(self_inner: Any) -> int:
                    return CAP  # inflight == cap → must reject

            return _R()

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    with pytest.raises(APIError) as exc_info:
        await tasks_mod.submit_task_core(
            _AtCapSession(),  # type: ignore[arg-type]
            settings=_settings,
            session_factory=lambda: None,
            docker_client=object(),
            shim_dispatcher=object(),
            tenant_id="ten_cap",
            cid="ctr_cap",
            body=TaskBody(prompt="hello cap"),
        )

    err = exc_info.value
    assert err.status_code == 429, f"Expected 429, got {err.status_code}"
    assert err.code == "too_many_tasks", f"Expected too_many_tasks, got {err.code!r}"

    # --- N-1 < CAP → cap check passes (any non-429 exit proves the gate cleared) ---

    class _BelowCapSession:
        async def execute(self, *a: Any, **k: Any) -> Any:
            class _R:
                def scalar_one(self_inner: Any) -> int:
                    return CAP - 1  # inflight == cap-1 → should be admitted

            return _R()

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    try:
        await tasks_mod.submit_task_core(
            _BelowCapSession(),  # type: ignore[arg-type]
            settings=_settings,
            session_factory=lambda: None,
            docker_client=object(),
            shim_dispatcher=object(),
            tenant_id="ten_cap",
            cid="ctr_cap",
            body=TaskBody(prompt="hello below cap"),
        )
    except APIError as exc:
        # If we get an APIError, it must NOT be a too_many_tasks rejection.
        assert exc.code != "too_many_tasks", (
            f"Cap check must NOT reject inflight={CAP - 1} (cap={CAP}); got {exc.code!r}"
        )
    except Exception:
        pass  # Any other error (e.g. credential lookup) confirms cap check was cleared.


# ===========================================================================
# Part 5 — outer fire-phase exception guard (scheduler.py lines 232-233)
# An exception from _submit_due_schedule must be logged+swallowed so one bad
# row never aborts the rest of the sweep.
# ===========================================================================


@pytest.mark.asyncio
async def test_sweep_fire_exception_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If _submit_due_schedule raises, the outer guard (lines 232-233) catches it
    and the sweep returns without re-raising — one failure can't kill the sweep."""

    class _FakeDueRow:
        id = "sch_boom"
        schedule = {"kind": "once"}
        timezone = "UTC"
        target = {"kind": "prompt", "container_id": "con_1", "prompt_id": "pmt_1"}

    async def fake_advance(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr(sched, "advance_workflow_runs", fake_advance)

    class _DB:
        def __init__(self) -> None:
            self._n = 0

        async def execute(self, *a: Any, **k: Any) -> Any:
            self._n += 1

            class _SelectResult:
                def all(self_inner: Any) -> list:
                    return [_FakeDueRow()]

            return _SelectResult() if self._n == 1 else object()

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    async def boom_submit(*, session: Any, row: Any, **kwargs: Any) -> None:
        raise RuntimeError("submit exploded")

    monkeypatch.setattr(sched, "_submit_due_schedule", boom_submit)

    # Must NOT propagate — sweep completes without raising.
    await sched.scheduler_sweep(
        _DB(), object(), object(),
        settings=object(),
        session_factory=lambda: None,
    )
