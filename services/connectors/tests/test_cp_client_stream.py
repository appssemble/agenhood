import httpx
import pytest

from connectors.cp_client import ControlPlaneClient

pytestmark = pytest.mark.unit

SSE = (
    "data: "
    '{"seq":1,"type":"assistant_message","ts":"t",'
    '"payload":{"content":[{"type":"text","text":"thinking"}]}}\n\n'
    "data: "
    '{"seq":2,"type":"status_change","ts":"t",'
    '"payload":{"from":"running","to":"succeeded",'
    '"result":{"output":"done"},"error":null}}\n\n'
)


@pytest.mark.asyncio
async def test_stream_events_parses_in_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("after_seq") == "0"
        return httpx.Response(200, text=SSE,
                              headers={"content-type": "text/event-stream"})

    client = ControlPlaneClient(base_url="http://cp",
                                transport=httpx.MockTransport(handler))
    seqs = []
    async for ev in client.stream_events(
        container_id="cnt_1", task_id="tsk_1", api_key="tk_live_x", after_seq=0
    ):
        seqs.append((ev["seq"], ev["type"]))
    assert seqs == [(1, "assistant_message"), (2, "status_change")]
