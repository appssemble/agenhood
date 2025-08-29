import pytest
from sqlalchemy import select

from control_plane.audit import audit
from control_plane.models_db import audit_log

pytestmark = [pytest.mark.integration]


async def test_audit_writes_row(db_session):
    # db_session: an AsyncSession against a migrated throwaway Postgres (fixture from conftest).
    await audit(
        db_session,
        actor_type="admin",
        actor_id="u_123",
        action="container.destroy",
        target_type="container",
        target_id="c_abc",
        details={"delete_volume": True},
    )
    await db_session.commit()

    rows = (await db_session.execute(select(audit_log))).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "admin"
    assert row["actor_id"] == "u_123"
    assert row["action"] == "container.destroy"
    assert row["target_type"] == "container"
    assert row["target_id"] == "c_abc"
    assert row["details"] == {"delete_volume": True}
    assert row["ts"] is not None


async def test_audit_failure_is_swallowed(db_session):
    # A broken session must not blow up the caller's main action.
    class Boom:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")

    # Should not raise.
    await audit(
        Boom(),
        actor_type="system",
        action="reconcile.error",
        target_type="container",
        target_id="c_x",
        details=None,
    )
