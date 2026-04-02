import httpx
import pytest

from connectors.cp_client import ControlPlaneClient

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_submit_task_posts_with_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.url.path
        import json
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "tsk_1", "status": "running",
                                         "started_at": "now"})

    client = ControlPlaneClient(
        base_url="http://cp", transport=httpx.MockTransport(handler)
    )
    task_id = await client.submit_task(
        container_id="cnt_1", api_key="tk_live_x",
        prompt="do it", metadata={"origin": "slack"},
    )
    assert task_id == "tsk_1"
    assert seen["auth"] == "Bearer tk_live_x"
    assert seen["path"] == "/v1/containers/cnt_1/tasks"
    assert seen["body"]["prompt"] == "do it"
    assert seen["body"]["metadata"] == {"origin": "slack"}
