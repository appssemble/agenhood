import asyncio

import pytest

from agentcore.drivers.codex_appserver import AppServerError
from agentcore.drivers.codex_spare import MAX_BUILD_FAILURES, SparePool, SpareRecipe, fingerprint

pytestmark = pytest.mark.unit


class FakeClient:
    def __init__(self, thread_id, fail=False):
        self.thread_id = thread_id
        self.fail = fail
        self.alive = True
        self.aborted = False
        self.requests = []

    async def request(self, method, params, timeout=None):  # noqa: ASYNC109
        self.requests.append((method, params))
        if self.fail:
            raise AppServerError("thread/start: refused")
        return {"thread": {"id": self.thread_id}}

    def abort(self):
        self.aborted = True
        self.alive = False


class FakeStarter:
    def __init__(self, *, fail_threads=False, fail_spawn=False):
        self.clients = []
        self.calls = []
        self.fail_threads = fail_threads
        self.fail_spawn = fail_spawn

    async def __call__(self, cmd, *, cwd, env):
        self.calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        if self.fail_spawn:
            raise AppServerError("initialize: boom")
        client = FakeClient(f"thr_{len(self.clients)}", fail=self.fail_threads)
        self.clients.append(client)
        return client


def recipe(model="m"):
    params = {"model": model, "cwd": "/w"}
    return SpareRecipe(cmd=["codex", "app-server"], cwd="/w", env={"A": "1"},
                       thread_params=params, fingerprint=fingerprint(model))


def pool(starter, *, capacity=True, max_age=600.0):
    p = SparePool(starter, max_age=max_age)
    p.set_capacity_check(lambda: capacity)
    return p


def test_fingerprint_is_stable_and_sensitive():
    assert fingerprint("a", {"x": 1, "y": 2}) == fingerprint("a", {"y": 2, "x": 1})
    assert fingerprint("a") != fingerprint("b")


@pytest.mark.asyncio
async def test_refill_builds_a_spare_that_claim_returns():
    starter = FakeStarter()
    p = pool(starter)
    r = recipe()
    p.remember(r)
    p.refill()
    await p.ready()

    assert starter.calls == [{"cmd": r.cmd, "cwd": r.cwd, "env": r.env}]
    assert starter.clients[0].requests == [("thread/start", r.thread_params)]
    spare, reason = await p.claim(r.fingerprint)
    assert reason == "hit"
    assert spare.thread_id == "thr_0"
    assert await p.claim(r.fingerprint) == (None, "none")


@pytest.mark.asyncio
async def test_refill_needs_a_recipe_and_capacity():
    starter = FakeStarter()
    p = pool(starter)
    p.refill()
    full = pool(starter, capacity=False)
    full.remember(recipe())
    full.refill()
    unset = SparePool(starter)
    unset.remember(recipe())
    unset.refill()
    await asyncio.sleep(0)
    assert starter.calls == []


@pytest.mark.asyncio
async def test_only_one_spare_at_a_time():
    starter = FakeStarter()
    p = pool(starter)
    p.remember(recipe())
    p.refill()
    p.refill()
    await p.ready()
    p.refill()
    await p.ready()
    assert len(starter.calls) == 1


@pytest.mark.asyncio
async def test_claim_with_other_settings_drops_the_spare():
    starter = FakeStarter()
    p = pool(starter)
    p.remember(recipe("a"))
    p.refill()
    await p.ready()

    assert await p.claim(fingerprint("b")) == (None, "settings_changed")
    assert starter.clients[0].aborted


@pytest.mark.asyncio
async def test_claim_waits_for_a_spare_being_built():
    starter = FakeStarter()
    p = pool(starter)
    r = recipe()
    p.remember(r)
    p.refill()
    spare, reason = await p.claim(r.fingerprint)
    assert reason == "hit"
    assert spare.thread_id == "thr_0"


@pytest.mark.asyncio
async def test_claim_while_building_other_settings_cancels_the_build():
    starter = FakeStarter()
    p = pool(starter)
    p.remember(recipe("a"))
    p.refill()
    assert await p.claim(fingerprint("b")) == (None, "settings_changed")
    await p.ready()
    assert await p.claim(fingerprint("a")) == (None, "none")


@pytest.mark.asyncio
async def test_dead_spare_is_reported():
    starter = FakeStarter()
    p = pool(starter)
    r = recipe()
    p.remember(r)
    p.refill()
    await p.ready()
    starter.clients[0].alive = False
    assert await p.claim(r.fingerprint) == (None, "dead")


@pytest.mark.asyncio
async def test_failed_builds_stop_after_the_limit_until_settings_change():
    starter = FakeStarter(fail_threads=True)
    p = pool(starter)
    p.remember(recipe("a"))
    for _ in range(MAX_BUILD_FAILURES + 2):
        p.refill()
        await p.ready()
    assert len(starter.calls) == MAX_BUILD_FAILURES
    assert all(c.aborted for c in starter.clients)
    assert await p.claim(fingerprint("a")) == (None, "warming_failed")

    p.remember(recipe("b"))
    p.refill()
    await p.ready()
    assert len(starter.calls) == MAX_BUILD_FAILURES + 1


@pytest.mark.asyncio
async def test_failed_spawn_counts_as_a_failure():
    starter = FakeStarter(fail_spawn=True)
    p = pool(starter)
    p.remember(recipe())
    p.refill()
    await p.ready()
    assert await p.claim(recipe().fingerprint) == (None, "warming_failed")


@pytest.mark.asyncio
async def test_spare_is_recycled_after_max_age():
    starter = FakeStarter()
    p = pool(starter, max_age=0.05)
    r = recipe()
    p.remember(r)
    p.refill()
    await p.ready()
    await asyncio.sleep(0.1)
    await p.ready()

    assert starter.clients[0].aborted
    spare, reason = await p.claim(r.fingerprint)
    assert reason == "hit"
    assert spare.thread_id == "thr_1"


@pytest.mark.asyncio
async def test_remember_none_turns_spares_off():
    starter = FakeStarter()
    p = pool(starter)
    p.remember(recipe())
    p.refill()
    await p.ready()
    p.remember(None)
    assert starter.clients[0].aborted
    p.refill()
    await asyncio.sleep(0)
    assert len(starter.calls) == 1


@pytest.mark.asyncio
async def test_close_stops_the_spare():
    starter = FakeStarter()
    p = pool(starter)
    p.remember(recipe())
    p.refill()
    await p.ready()
    await p.close()
    assert starter.clients[0].aborted
    p.refill()
    await asyncio.sleep(0)
    assert len(starter.calls) == 1
