import pytest

from control_plane import dormant

pytestmark = pytest.mark.unit


class _SweepDB:
    """Returns candidates when the SQL filters on *status_token*; records commit/rollback.

    The dormant sweeps run a guarded lifecycle op per candidate and must commit each
    one — without a commit the transition rolls back when the sweep's session closes.
    """

    def __init__(self, status_token: str, candidates: list[str]) -> None:
        self.status_token = status_token
        self.candidates = candidates
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        cands = self.candidates if self.status_token in str(stmt).lower() else []

        class R:
            rowcount = 1

            def fetchall(self_):
                return [(c,) for c in cands]

            def first(self_):
                return None

        return R()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_archive_sweep_archives_each_eligible_paused(monkeypatch):
    archived = []
    async def fake_archive(db, dock, cid): archived.append(cid)
    monkeypatch.setattr(dormant.lifecycle, "archive", fake_archive)

    await dormant.archive_sweep(_SweepDB("status = 'paused'", ["con_1", "con_2"]),
                                object(), shim=None)
    assert archived == ["con_1", "con_2"]


@pytest.mark.asyncio
async def test_archive_sweep_commits_each_archive(monkeypatch):
    async def fake_archive(db, dock, cid): return None
    monkeypatch.setattr(dormant.lifecycle, "archive", fake_archive)

    db = _SweepDB("status = 'paused'", ["con_1", "con_2"])
    await dormant.archive_sweep(db, object(), shim=None)
    assert db.commits == 2
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_archive_sweep_rolls_back_on_error(monkeypatch):
    async def fake_archive(db, dock, cid):
        if cid == "boom":
            raise RuntimeError("docker exploded")
    monkeypatch.setattr(dormant.lifecycle, "archive", fake_archive)

    db = _SweepDB("status = 'paused'", ["boom", "con_ok"])
    await dormant.archive_sweep(db, object(), shim=None)
    assert db.commits == 1
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_reclaim_sweep_reclaims_each_eligible_archived(monkeypatch):
    reclaimed = []
    async def fake_reclaim(db, dock, cid): reclaimed.append(cid)
    monkeypatch.setattr(dormant, "reclaim_one", fake_reclaim)

    await dormant.reclaim_sweep(_SweepDB("status = 'archived'", ["con_9"]),
                                object(), shim=None)
    assert reclaimed == ["con_9"]


@pytest.mark.asyncio
async def test_reclaim_sweep_commits_each_reclaim(monkeypatch):
    async def fake_reclaim(db, dock, cid): return None
    monkeypatch.setattr(dormant, "reclaim_one", fake_reclaim)

    db = _SweepDB("status = 'archived'", ["con_9", "con_10"])
    await dormant.reclaim_sweep(db, object(), shim=None)
    assert db.commits == 2
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_reclaim_sweep_rolls_back_on_error(monkeypatch):
    async def fake_reclaim(db, dock, cid):
        if cid == "boom":
            raise RuntimeError("volume gone")
    monkeypatch.setattr(dormant, "reclaim_one", fake_reclaim)

    db = _SweepDB("status = 'archived'", ["boom", "con_ok"])
    await dormant.reclaim_sweep(db, object(), shim=None)
    assert db.commits == 1
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_reclaim_one_deletes_volume_and_destroys(monkeypatch):
    seq = []
    async def t(db, cid, expected, new):
        seq.append((expected, new))
        return True
    async def vrm(client, vol): seq.append(("vrm", vol))
    async def setf(db, cid, **kw): seq.append(("set", kw))
    monkeypatch.setattr(dormant.lifecycle, "transition", t)
    monkeypatch.setattr(dormant.docker_ctl, "volume_rm", vrm)
    monkeypatch.setattr(dormant.lifecycle, "_set", setf)
    monkeypatch.setattr(dormant.lifecycle, "_load",
                        lambda db, cid: _row())
    await dormant.reclaim_one(_DB(), object(), "con_9")
    assert ("archived", "destroying") in seq
    assert ("vrm", "agent-vol-9") in seq
    assert ("destroying", "destroyed") in seq


async def _row():
    return {"id": "con_9", "volume_name": "agent-vol-9"}


class _DB:
    async def execute(self, *a, **k):
        class R:
            rowcount = 1
            def first(self_): return None
        return R()
