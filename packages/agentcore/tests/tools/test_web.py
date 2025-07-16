# packages/agentcore/tests/tools/test_web.py
import asyncio
import pathlib

import httpx
import pytest
import respx

from agentcore.tools.base import ToolContext
from agentcore.tools.web import WebFetchTool, WebSearchTool

pytestmark = pytest.mark.unit

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

SEARXNG_JSON = {
    "query": "self-hosted email",
    "results": [
        {
            "title": "Listmonk",
            "url": "https://listmonk.app",
            "content": "Self-hosted newsletter manager.",
        },
        {
            "title": "Mautic",
            "url": "https://mautic.org",
            "content": "Marketing automation you can self-host.",
        },
    ],
}


def ctx(tmp_path):
    return ToolContext(workspace=str(tmp_path), cancel=asyncio.Event())


@respx.mock
@pytest.mark.asyncio
async def test_web_search_parses_searxng_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    res = await WebSearchTool().run({"query": "self-hosted email"}, ctx(tmp_path))
    assert res.ok
    assert "Listmonk" in res.content
    assert "https://listmonk.app" in res.content
    assert "Self-hosted newsletter manager." in res.content
    assert "Mautic" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_format_json_param_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    route = respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    await WebSearchTool().run({"query": "x"}, ctx(tmp_path))
    sent = route.calls.last.request
    assert sent.url.params["format"] == "json"
    assert sent.url.params["q"] == "x"


@respx.mock
@pytest.mark.asyncio
async def test_web_fetch_text_mode_extracts_content(tmp_path):
    html = (FIXTURES / "article.html").read_text()
    respx.get("https://example.test/article").mock(
        return_value=httpx.Response(
            200, html=html, headers={"content-type": "text/html"}
        )
    )
    res = await WebFetchTool().run(
        {"url": "https://example.test/article", "mode": "text"}, ctx(tmp_path)
    )
    assert res.ok
    assert "Listmonk" in res.content
    assert "Mautic" in res.content
    # boilerplate stripped by trafilatura
    assert "Home About Contact" not in res.content


@pytest.mark.asyncio
async def test_web_fetch_rendered_requires_chromium_feature(tmp_path, monkeypatch):
    # No chromium present in the test env → tool reports the missing feature.
    monkeypatch.delenv("AGENT_IMAGE_VARIANT", raising=False)
    res = await WebFetchTool().run(
        {"url": "https://example.test/x", "mode": "rendered"}, ctx(tmp_path)
    )
    assert not res.ok
    assert "chromium" in res.content.lower()


def test_web_fetch_declares_no_driver_feature_but_rendered_needs_chromium():
    # The tool itself is enabled on slim too (text mode); the rendered-mode
    # requirement is enforced at call time, and the spec marks the feature.
    assert WebFetchTool().spec.requires_image_feature == "chromium"


def test_web_tools_self_register():
    import agentcore.tools.web  # noqa: F401
    from agentcore.tools.base import TOOLS
    assert "web_search" in TOOLS
    assert "web_fetch" in TOOLS
