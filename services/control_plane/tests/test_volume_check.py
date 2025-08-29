import pytest

from control_plane import volume_check

pytestmark = pytest.mark.unit


def test_over_limit_is_strict_greater_than():
    assert volume_check.over_limit_mb(10241, 10240) is True
    assert volume_check.over_limit_mb(10240, 10240) is False   # exactly at cap is allowed
    assert volume_check.over_limit_mb(5000, 10240) is False


@pytest.mark.asyncio
async def test_sweep_alerts_only_oversize_volumes(monkeypatch):
    alerted = []

    async def fake_audit(session, **kw):
        alerted.append((kw["target_id"], kw["details"]["used_mb"], kw["details"]["limit_mb"]))

    monkeypatch.setattr(volume_check, "audit", fake_audit)

    # Two containers; con_big is over its tenant's 10240 MB cap, con_ok is under.
    class DB:
        async def execute(self, stmt, params=None):
            class R:
                def fetchall(self_):
                    return [
                        ("con_big", "vol_big", 10240),
                        ("con_ok", "vol_ok", 10240),
                    ]
            return R()

    async def fake_measure(client, volume_name):
        return {"vol_big": 12000, "vol_ok": 3000}[volume_name]

    n = await volume_check.volume_size_sweep(DB(), object(), measure=fake_measure)
    assert n == 1                                   # one alert emitted
    assert alerted == [("con_big", 12000, 10240)]   # only the oversize volume
