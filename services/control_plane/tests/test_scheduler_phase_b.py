# services/control_plane/tests/test_scheduler_phase_b.py
import pytest
import control_plane.scheduler as scheduler_mod

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_sweep_calls_advance_before_due_query(monkeypatch):
    order: list[str] = []

    async def fake_advance(db, docker_client, shim, *, settings, session_factory):
        order.append("advance")

    monkeypatch.setattr(scheduler_mod, "advance_workflow_runs", fake_advance)

    class _DB:
        async def execute(self, *a, **k):
            order.append("due_query")
            class _R:
                def all(self_inner):
                    return []
            return _R()
        async def commit(self):
            pass

    await scheduler_mod.scheduler_sweep(
        _DB(), object(), object(), settings=object(), session_factory=lambda: None)
    assert order and order[0] == "advance"
