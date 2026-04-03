import pytest

from connectors.relay import run_relay

pytestmark = pytest.mark.unit


class FakeProvider:
    def __init__(self):
        self.posts = []
        self.updates = []

    async def post_initial(self, token, origin_ref, body):
        self.posts.append(body)
        return {"channel": "C1", "ts": "100"}

    async def update_message(self, token, handle, body):
        self.updates.append(body)


async def _fake_events():
    yield {"seq": 1, "type": "assistant_message",
           "payload": {"content": [{"type": "text", "text": "thinking hard"}]}}
    yield {"seq": 2, "type": "status_change",
           "payload": {"to": "succeeded", "result": {"output": "FINISHED"}, "error": None}}


@pytest.mark.asyncio
async def test_relay_streams_and_finalizes():
    provider = FakeProvider()
    saved = {}

    async def save_progress(last_seq, state):
        saved["last_seq"] = last_seq
        saved["state"] = state

    await run_relay(
        events=_fake_events(),
        provider=provider,
        token="tok",
        origin_ref={"channel": "C1", "thread_ts": "100"},
        surface=["reasoning", "result"],
        coalesce_ms=0,  # flush every event in tests
        save_progress=save_progress,
    )
    assert provider.posts  # initial message posted
    assert any("thinking hard" in u for u in provider.updates)
    assert any("FINISHED" in u for u in provider.updates)
    assert saved["last_seq"] == 2
    assert saved["state"] == "done"
