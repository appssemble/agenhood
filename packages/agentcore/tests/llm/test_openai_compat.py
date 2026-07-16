import json

import httpx
import pytest
import respx

from agentcore.llm.openai_compat import OpenAICompatClient

pytestmark = pytest.mark.unit

OPENAI_RESPONSE = {
    "id": "chatcmpl_01",
    "object": "chat.completion",
    "model": "gpt-x",
    "choices": [{
        "index": 0,
        "finish_reason": "tool_calls",
        "message": {
            "role": "assistant",
            "content": "let me search",
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "web_search",
                             "arguments": "{\"query\": \"foo\"}"},
            }],
        },
    }],
    "usage": {"prompt_tokens": 42, "completion_tokens": 7},
}


@respx.mock
@pytest.mark.asyncio
async def test_create_translates_request_and_response():
    route = respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=OPENAI_RESPONSE)
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")

    resp = await client.create(
        model="gpt-x",
        system="you are a helper",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "call_0", "name": "read_file",
                 "input": {"path": "a.txt"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_0",
                 "content": "file body", "is_error": False},
            ]},
        ],
        tools=[{"name": "web_search", "description": "d",
                "input_schema": {"type": "object"}}],
        max_tokens=4096,
        credential="sk-secret",
    )

    # Response mapped back to Anthropic-style blocks.
    assert resp.content == [
        {"type": "text", "text": "let me search"},
        {"type": "tool_use", "id": "call_1", "name": "web_search",
         "input": {"query": "foo"}},
    ]
    assert resp.tokens_in == 42
    assert resp.tokens_out == 7
    assert resp.stop_reason == "tool_use"

    # Request wire format.
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-secret"
    payload = json.loads(sent.content)
    assert payload["model"] == "gpt-x"
    assert payload["max_tokens"] == 4096
    assert payload["messages"][0] == {"role": "system", "content": "you are a helper"}
    assert payload["messages"][1] == {"role": "user", "content": "hi"}
    assistant = payload["messages"][2]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "checking"
    assert assistant["tool_calls"] == [{
        "id": "call_0", "type": "function",
        "function": {"name": "read_file",
                     "arguments": json.dumps({"path": "a.txt"})},
    }]
    assert payload["messages"][3] == {
        "role": "tool", "tool_call_id": "call_0", "content": "file body",
    }
    assert payload["tools"] == [{
        "type": "function",
        "function": {"name": "web_search", "description": "d",
                     "parameters": {"type": "object"}},
    }]


@respx.mock
@pytest.mark.asyncio
async def test_max_completion_tokens_flag():
    route = respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=OPENAI_RESPONSE)
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1",
                                use_max_completion_tokens=True)
    await client.create(model="gpt-x", system="", messages=[], tools=[],
                        max_tokens=1024, credential="sk")
    payload = json.loads(route.calls.last.request.content)
    assert payload["max_completion_tokens"] == 1024
    assert "max_tokens" not in payload


def _envelope(message: dict, finish: str = "stop", usage: dict | None = None) -> dict:
    return {
        "id": "chatcmpl_02", "object": "chat.completion", "model": "gpt-x",
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        **({"usage": usage} if usage is not None else {}),
    }


@respx.mock
@pytest.mark.asyncio
async def test_malformed_tool_arguments_dropped_with_note():
    respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_envelope(
            {"role": "assistant", "content": None,
             "tool_calls": [
                 {"id": "bad", "type": "function",
                  "function": {"name": "done", "arguments": "{not json"}},
                 {"id": "ok", "type": "function",
                  "function": {"name": "list_files", "arguments": "{}"}},
             ]},
            finish="tool_calls",
        ))
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    resp = await client.create(model="gpt-x", system="", messages=[], tools=[],
                               max_tokens=10, credential="sk")
    # Malformed call became a text note; the parseable one survived.
    assert resp.content[0]["type"] == "text"
    assert "dropped" in resp.content[0]["text"]
    assert resp.content[1] == {"type": "tool_use", "id": "ok",
                               "name": "list_files", "input": {}}


@respx.mock
@pytest.mark.asyncio
async def test_missing_usage_counts_zero_and_stop_maps_to_end_turn():
    respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_envelope(
            {"role": "assistant", "content": "all done"}, finish="stop",
        ))
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    resp = await client.create(model="gpt-x", system="", messages=[], tools=[],
                               max_tokens=10, credential="sk")
    assert resp.tokens_in == 0 and resp.tokens_out == 0
    assert resp.stop_reason == "end_turn"
    assert resp.content == [{"type": "text", "text": "all done"}]


@respx.mock
@pytest.mark.asyncio
async def test_null_usage_counts_zero():
    respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_envelope(
            {"role": "assistant", "content": "all done"}, finish="stop",
            usage={"prompt_tokens": None, "completion_tokens": None},
        ))
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    resp = await client.create(model="gpt-x", system="", messages=[], tools=[],
                               max_tokens=10, credential="sk")
    assert resp.tokens_in == 0 and resp.tokens_out == 0


@respx.mock
@pytest.mark.asyncio
async def test_empty_assistant_history_turn_round_trips_as_placeholder():
    """An empty assistant turn (no text, no tool_use) must not become
    content=None on the next request — OpenAI rejects null content without
    tool_calls, which would kill the loop's nudge recovery."""
    route = respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=OPENAI_RESPONSE)
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    await client.create(
        model="gpt-x", system="",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": []},   # empty prior completion
            {"role": "user", "content": "You must call the `done` tool to finish."},
        ],
        tools=[], max_tokens=10, credential="sk",
    )
    payload = json.loads(route.calls.last.request.content)
    assistant = payload["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"]            # not None / not empty
    assert "tool_calls" not in assistant


@respx.mock
@pytest.mark.asyncio
async def test_length_finish_maps_to_max_tokens():
    respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_envelope(
            {"role": "assistant", "content": "truncat"}, finish="length",
            usage={"prompt_tokens": 1, "completion_tokens": 2},
        ))
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    resp = await client.create(model="gpt-x", system="", messages=[], tools=[],
                               max_tokens=10, credential="sk")
    assert resp.stop_reason == "max_tokens"


@respx.mock
@pytest.mark.asyncio
async def test_create_raises_on_api_error():
    respx.post("https://stub.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            401, json={"error": {"type": "invalid_request_error",
                                 "message": "bad key"}}
        )
    )
    client = OpenAICompatClient(base_url="https://stub.test/v1")
    with pytest.raises(RuntimeError, match="bad key"):
        await client.create(model="gpt-x", system="", messages=[], tools=[],
                            max_tokens=10, credential="sk")
