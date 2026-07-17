# packages/agentcore/tests/tools/test_web.py
import asyncio
import pathlib
import sys
import types

import httpx
import pytest
import respx

from agentcore.tools.base import ToolContext
from agentcore.tools.web import WebFetchTool, WebReadTool, WebSearchTool

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


@pytest.fixture(autouse=True)
def _no_ambient_exa_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)


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


@pytest.mark.asyncio
async def test_web_fetch_missing_url_is_error_result(tmp_path):
    res = await WebFetchTool().run({}, ctx(tmp_path))
    assert not res.ok  # must not raise KeyError


@pytest.mark.asyncio
async def test_web_fetch_rendered_truncates_with_marker(tmp_path, monkeypatch):
    # Simulate the full image variant (chromium present) with a fake playwright
    # module so the rendered path can be exercised without a real browser.
    monkeypatch.setattr("agentcore.tools.web._chromium_path", lambda: "/usr/bin/chromium")

    huge_html = "<html><body>" + ("hello world " * 500_000) + "</body></html>"

    class FakePage:
        async def goto(self, url, **kwargs):
            pass

        async def content(self):
            return huge_html

    class FakeBrowser:
        async def new_page(self):
            return FakePage()

        async def close(self):
            pass

    class FakeChromiumLauncher:
        async def launch(self, executable_path, args):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromiumLauncher()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: FakePlaywright()  # type: ignore[attr-defined]
    fake_playwright = types.ModuleType("playwright")
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    res = await WebFetchTool().run(
        {"url": "https://example.test/huge", "mode": "rendered"}, ctx(tmp_path)
    )
    assert res.ok
    assert len(res.content.encode("utf-8")) <= 5 * 1024 * 1024 + 200
    assert "truncated" in res.content.lower()


def test_web_tools_self_register():
    import agentcore.tools.web  # noqa: F401
    from agentcore.tools.base import TOOLS
    assert "web_search" in TOOLS
    assert "web_fetch" in TOOLS


WIKIPEDIA_JSON = {
    "pages": [
        {
            "id": 41940,
            "key": "Bucharest",
            "title": "Bucharest",
            "excerpt": '<span class="searchmatch">Bucharest</span> is the capital of Romania.',
            "description": "capital and largest city of Romania",
        },
        {
            "id": 25445,
            "key": "Romania",
            "title": "Romania",
            "excerpt": "Romania is a country in Europe.",
            "description": "country in Europe",
        },
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_web_search_empty_with_unresponsive_engines_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [],
            "unresponsive_engines": [["duckduckgo", "CAPTCHA"], ["brave", "too many requests"]],
        })
    )
    # Wikipedia floor is also down → the original degraded error must surface.
    respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(500)
    )
    res = await WebSearchTool().run({"query": "calories"}, ctx(tmp_path))
    assert not res.ok
    assert "degraded" in res.content
    assert "duckduckgo (CAPTCHA)" in res.content
    assert "brave (too many requests)" in res.content
    assert "retrying the same search will not help" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_degraded_falls_back_to_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [],
            "unresponsive_engines": [["brave", "too many requests"]],
        })
    )
    wiki = respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(200, json=WIKIPEDIA_JSON)
    )
    res = await WebSearchTool().run({"query": "bucharest"}, ctx(tmp_path))
    assert res.ok
    # honest degradation header so the model can adapt
    assert "degraded" in res.content
    assert "Wikipedia" in res.content
    assert "brave (too many requests)" in res.content
    # formatted like normal results: title, url built from page key, excerpt
    assert "Bucharest" in res.content
    assert "https://en.wikipedia.org/wiki/Bucharest" in res.content
    assert "is the capital of Romania" in res.content
    # HTML stripped from excerpts
    assert "searchmatch" not in res.content
    assert wiki.calls.last.request.url.params["q"] == "bucharest"
    # Wikimedia 403s default library User-Agents; a descriptive one is required.
    ua = wiki.calls.last.request.headers["user-agent"]
    assert "agenhood" in ua and "python-httpx" not in ua


@respx.mock
@pytest.mark.asyncio
async def test_web_search_searxng_error_falls_back_to_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(200, json=WIKIPEDIA_JSON)
    )
    res = await WebSearchTool().run({"query": "bucharest"}, ctx(tmp_path))
    assert res.ok
    assert "degraded" in res.content
    assert "Wikipedia" in res.content
    assert "https://en.wikipedia.org/wiki/Bucharest" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_searxng_error_and_wiki_error_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(500)
    )
    res = await WebSearchTool().run({"query": "x"}, ctx(tmp_path))
    assert not res.ok
    assert "search failed" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_genuine_no_results_does_not_hit_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    )
    wiki = respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(200, json=WIKIPEDIA_JSON)
    )
    res = await WebSearchTool().run({"query": "zxqv-no-hit"}, ctx(tmp_path))
    assert res.ok
    assert res.content == "(no results)"
    assert not wiki.called


@respx.mock
@pytest.mark.asyncio
async def test_web_search_healthy_does_not_hit_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    wiki = respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(200, json=WIKIPEDIA_JSON)
    )
    res = await WebSearchTool().run({"query": "self-hosted email"}, ctx(tmp_path))
    assert res.ok
    assert "Listmonk" in res.content
    assert "degraded" not in res.content
    assert not wiki.called


@respx.mock
@pytest.mark.asyncio
async def test_web_search_empty_without_unresponsive_engines_stays_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    )
    res = await WebSearchTool().run({"query": "zxqv-no-hit"}, ctx(tmp_path))
    assert res.ok
    assert res.content == "(no results)"


@respx.mock
@pytest.mark.asyncio
async def test_web_search_results_with_partial_engine_failure_stays_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    payload = dict(SEARXNG_JSON)
    payload["unresponsive_engines"] = [["brave", "too many requests"]]
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=payload)
    )
    res = await WebSearchTool().run({"query": "self-hosted email"}, ctx(tmp_path))
    assert res.ok
    assert "Listmonk" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_malformed_unresponsive_engines_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={"results": [], "unresponsive_engines": "weird"})
    )
    res = await WebSearchTool().run({"query": "x"}, ctx(tmp_path))
    # Malformed metadata must not crash; treat as degraded-unknown or no-results,
    # but NEVER raise. Accept either verdict as long as it returns cleanly.
    assert isinstance(res.content, str)


EXA_SEARCH_JSON = {
    "results": [
        {
            "title": "Calorii paine cu pate",
            "url": "https://calorii.example/paine-pate",
            "highlights": ["250 kcal per 100g"],
        }
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_web_search_uses_exa_when_keyed(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k-123")
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    exa = respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json=EXA_SEARCH_JSON)
    )
    searx = respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    res = await WebSearchTool().run({"query": "paine cu pate calorii"}, ctx(tmp_path))
    assert res.ok
    assert "Calorii paine cu pate" in res.content
    assert "https://calorii.example/paine-pate" in res.content
    assert "250 kcal per 100g" in res.content
    assert "note:" not in res.content
    assert exa.called
    assert not searx.called


@respx.mock
@pytest.mark.asyncio
async def test_web_search_exa_failure_falls_back_to_searxng_with_note(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k-123")
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(500))
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    res = await WebSearchTool().run({"query": "self-hosted email"}, ctx(tmp_path))
    assert res.ok
    assert res.content.startswith("note: primary search (exa) failed")
    assert "results from fallback search:" in res.content
    assert "Listmonk" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_unkeyed_never_calls_exa(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    exa = respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json=EXA_SEARCH_JSON)
    )
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json=SEARXNG_JSON)
    )
    res = await WebSearchTool().run({"query": "self-hosted email"}, ctx(tmp_path))
    assert res.ok
    assert "Listmonk" in res.content
    assert "note:" not in res.content
    assert not exa.called


@respx.mock
@pytest.mark.asyncio
async def test_web_search_exa_fails_searxng_degraded_reaches_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k-123")
    monkeypatch.setenv("SEARCH_PROVIDER_URL", "http://searxng.test:8080")
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(500))
    respx.get("http://searxng.test:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [],
            "unresponsive_engines": [["brave", "too many requests"]],
        })
    )
    respx.get("https://en.wikipedia.org/w/rest.php/v1/search/page").mock(
        return_value=httpx.Response(200, json=WIKIPEDIA_JSON)
    )
    res = await WebSearchTool().run({"query": "bucharest"}, ctx(tmp_path))
    assert res.ok
    assert res.content.startswith("note: primary search (exa) failed")
    assert "Wikipedia" in res.content
    assert "https://en.wikipedia.org/wiki/Bucharest" in res.content


@respx.mock
@pytest.mark.asyncio
async def test_web_search_ctx_env_key_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    exa = respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json=EXA_SEARCH_JSON)
    )
    context = ToolContext(
        workspace=str(tmp_path), cancel=asyncio.Event(), env={"EXA_API_KEY": "ctx-key"}
    )
    res = await WebSearchTool().run({"query": "x"}, context)
    assert res.ok
    assert exa.calls.last.request.headers["x-api-key"] == "ctx-key"


EXA_CONTENTS_JSON = {
    "results": [{"url": "https://a.example/p", "title": "P", "text": "# Title\n\nClean article body."}]
}


@respx.mock
@pytest.mark.asyncio
async def test_web_read_uses_exa_when_keyed(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k-123")
    exa = respx.post("https://api.exa.ai/contents").mock(
        return_value=httpx.Response(200, json=EXA_CONTENTS_JSON)
    )
    res = await WebReadTool().run({"url": "https://a.example/p"}, ctx(tmp_path))
    assert res.ok
    assert res.content == "# Title\n\nClean article body."
    assert exa.called


@respx.mock
@pytest.mark.asyncio
async def test_web_read_unkeyed_falls_back_to_local_fetch(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    html = (FIXTURES / "article.html").read_text()
    exa = respx.post("https://api.exa.ai/contents").mock(
        return_value=httpx.Response(200, json=EXA_CONTENTS_JSON)
    )
    respx.get("https://example.test/article").mock(
        return_value=httpx.Response(200, html=html, headers={"content-type": "text/html"})
    )
    res = await WebReadTool().run({"url": "https://example.test/article"}, ctx(tmp_path))
    assert res.ok
    assert "Listmonk" in res.content
    assert "note:" not in res.content
    assert not exa.called


@respx.mock
@pytest.mark.asyncio
async def test_web_read_exa_failure_degrades_to_local_fetch_with_note(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k-123")
    html = (FIXTURES / "article.html").read_text()
    respx.post("https://api.exa.ai/contents").mock(return_value=httpx.Response(500))
    respx.get("https://example.test/article").mock(
        return_value=httpx.Response(200, html=html, headers={"content-type": "text/html"})
    )
    res = await WebReadTool().run({"url": "https://example.test/article"}, ctx(tmp_path))
    assert res.ok
    assert res.content.startswith("note: hosted read (exa) failed")
    assert "Listmonk" in res.content


@pytest.mark.asyncio
async def test_web_read_missing_url_is_error_result(tmp_path):
    res = await WebReadTool().run({}, ctx(tmp_path))
    assert not res.ok


def test_web_read_spec_slim_safe_and_registered():
    from agentcore.tools.base import TOOLS
    assert WebReadTool().spec.requires_image_feature is None
    assert "web_read" in TOOLS


def test_web_read_in_vanilla_template():
    from agentcore.drivers.vanilla import VanillaDriver
    assert "web_read" in VanillaDriver.default_template.available_tools
