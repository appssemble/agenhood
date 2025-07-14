import httpx
import pytest
import respx

from agentcore.llm.anthropic import AnthropicClient

pytestmark = pytest.mark.unit

ANTHROPIC_RESPONSE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-x",
    "stop_reason": "tool_use",
    "content": [
        {"type": "text", "text": "let me search"},
        {"type": "tool_use", "id": "tu_1", "name": "web_search",
         "input": {"query": "foo"}},
    ],
    "usage": {"input_tokens": 42, "output_tokens": 7},
}


@respx.mock
@pytest.mark.asyncio
async def test_create_parses_response_and_sends_correct_wire():
    route = respx.post("https://stub.test/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    client = AnthropicClient(base_url="https://stub.test")

    resp = await client.create(
        model="claude-x",
        system="you are a helper",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "web_search", "description": "d", "input_schema": {}}],
        max_tokens=4096,
        credential="sk-secret",
    )

    assert resp.content == ANTHROPIC_RESPONSE["content"]
    assert resp.tokens_in == 42
    assert resp.tokens_out == 7
    assert resp.stop_reason == "tool_use"

    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-secret"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    body = httpx.Response(200, request=sent).request.content
    import json
    payload = json.loads(body)
    assert payload["model"] == "claude-x"
    assert payload["system"] == "you are a helper"
    assert payload["max_tokens"] == 4096
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["tools"][0]["name"] == "web_search"


@respx.mock
@pytest.mark.asyncio
async def test_create_raises_on_api_error():
    respx.post("https://stub.test/v1/messages").mock(
        return_value=httpx.Response(
            400, json={"type": "error",
                       "error": {"type": "invalid_request_error", "message": "bad"}}
        )
    )
    client = AnthropicClient(base_url="https://stub.test")
    with pytest.raises(RuntimeError, match="bad"):
        await client.create(
            model="claude-x", system="", messages=[], tools=[],
            max_tokens=10, credential="sk",
        )
