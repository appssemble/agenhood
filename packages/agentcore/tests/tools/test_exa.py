# packages/agentcore/tests/tools/test_exa.py
import asyncio

import httpx
import pytest
import respx

from agentcore.tools.base import ToolContext
from agentcore.tools.exa import ExaError, exa_api_key, exa_contents, exa_search

pytestmark = pytest.mark.unit

SEARCH_JSON = {
    "results": [
        {
            "title": "Calorii paine cu pate",
            "url": "https://calorii.example/paine-pate",
            "highlights": ["Paine cu pate are 250 kcal", "per 100g"],
        },
        {
            "title": "Nutrition facts",
            "url": "https://nutri.example/x",
            "text": "Long article text about bread and pate nutrition values.",
        },
    ]
}

CONTENTS_JSON = {
    "results": [
        {"url": "https://a.example/page", "title": "Page", "text": "# Heading\n\nBody text."}
    ]
}


def ctx(env=None):
    return ToolContext(workspace="/tmp", cancel=asyncio.Event(), env=env or {})


def test_exa_api_key_prefers_ctx_env_over_process_env(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "from-process")
    assert exa_api_key(ctx({"EXA_API_KEY": "from-ctx"})) == "from-ctx"
    assert exa_api_key(ctx()) == "from-process"
    monkeypatch.delenv("EXA_API_KEY")
    assert exa_api_key(ctx()) == ""


@respx.mock
@pytest.mark.asyncio
async def test_exa_search_parses_results_and_sends_key():
    route = respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json=SEARCH_JSON)
    )
    out = await exa_search("paine cu pate calorii", "k-123", limit=8)
    assert out[0] == {
        "title": "Calorii paine cu pate",
        "url": "https://calorii.example/paine-pate",
        "snippet": "Paine cu pate are 250 kcal per 100g",
    }
    # text-only result falls back to a text prefix as snippet
    assert out[1]["snippet"].startswith("Long article text")
    req = route.calls.last.request
    assert req.headers["x-api-key"] == "k-123"
    import json as _json
    body = _json.loads(req.content)
    assert body["query"] == "paine cu pate calorii"
    assert body["numResults"] == 8
    assert body["type"] == "auto"


@respx.mock
@pytest.mark.asyncio
async def test_exa_search_http_error_raises_exa_error():
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(401))
    with pytest.raises(ExaError):
        await exa_search("q", "bad-key")


@respx.mock
@pytest.mark.asyncio
async def test_exa_search_empty_results_raises_exa_error():
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(ExaError):
        await exa_search("q", "k")


@respx.mock
@pytest.mark.asyncio
async def test_exa_search_network_error_raises_exa_error():
    respx.post("https://api.exa.ai/search").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with pytest.raises(ExaError):
        await exa_search("q", "k")


@respx.mock
@pytest.mark.asyncio
async def test_exa_contents_returns_text():
    route = respx.post("https://api.exa.ai/contents").mock(
        return_value=httpx.Response(200, json=CONTENTS_JSON)
    )
    text = await exa_contents("https://a.example/page", "k-123")
    assert text == "# Heading\n\nBody text."
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body["urls"] == ["https://a.example/page"]
    assert body["text"] is True


@respx.mock
@pytest.mark.asyncio
async def test_exa_contents_missing_text_raises_exa_error():
    respx.post("https://api.exa.ai/contents").mock(
        return_value=httpx.Response(200, json={"results": [{"url": "x"}]})
    )
    with pytest.raises(ExaError):
        await exa_contents("https://a.example/page", "k")
