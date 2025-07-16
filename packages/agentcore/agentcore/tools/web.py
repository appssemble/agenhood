from __future__ import annotations

import os
import shutil
import time
from typing import Any

import httpx

from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms, register

DEFAULT_SEARCH_URL = "http://searxng:8080"
MAX_FETCH_BYTES = 5 * 1024 * 1024  # 5 MiB
SEARCH_RESULT_LIMIT = 8


class WebSearchTool:
    spec = ToolSpec(
        name="web_search",
        description=(
            "Search the web via the internal SearXNG service. "
            "Returns title, URL, and snippet for the top results."
        ),
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        base = os.environ.get("SEARCH_PROVIDER_URL", DEFAULT_SEARCH_URL).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.get(
                    f"{base}/search",
                    params={"q": input["query"], "format": "json"},
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001 — surface network/parse errors to the model
            return ToolResult(
                ok=False, content=f"search failed: {e}", duration_ms=_ms(start)
            )

        results = data.get("results", [])[:SEARCH_RESULT_LIMIT]
        if not results:
            return ToolResult(ok=True, content="(no results)", duration_ms=_ms(start))
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        return ToolResult(ok=True, content="\n".join(lines), duration_ms=_ms(start))


def _chromium_path() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser")


class WebFetchTool:
    spec = ToolSpec(
        name="web_fetch",
        description=(
            "Fetch a URL and extract readable content as markdown. "
            "mode='text' uses httpx+trafilatura; mode='rendered' uses headless "
            "Chromium (requires the full image variant)."
        ),
        input_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "mode": {"type": "string", "enum": ["text", "rendered"]},
            },
        },
        requires_image_feature="chromium",
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        mode = input.get("mode", "text")
        url = input["url"]
        if mode == "rendered":
            return await self._rendered(url, start)
        return await self._text(url, start)

    async def _text(self, url: str, start: float) -> ToolResult:
        import trafilatura

        try:
            async with httpx.AsyncClient(
                timeout=60.0, follow_redirects=True
            ) as http:
                resp = await http.get(url)
            resp.raise_for_status()
            raw = resp.content[:MAX_FETCH_BYTES]
            html = raw.decode(resp.encoding or "utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                ok=False, content=f"fetch failed: {e}", duration_ms=_ms(start)
            )
        extracted = trafilatura.extract(html, output_format="markdown")
        if not extracted:
            return ToolResult(
                ok=False,
                content="could not extract readable content; try mode='rendered'",
                duration_ms=_ms(start),
            )
        if len(resp.content) > MAX_FETCH_BYTES:
            extracted += "\n[...response truncated at 5 MiB...]"
        return ToolResult(ok=True, content=extracted, duration_ms=_ms(start))

    async def _rendered(self, url: str, start: float) -> ToolResult:
        if _chromium_path() is None:
            return ToolResult(
                ok=False,
                content=(
                    "rendered mode requires chromium, which is only present in the "
                    "full image variant; use mode='text' or run on a full container"
                ),
                duration_ms=_ms(start),
            )
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
        except ImportError:
            return ToolResult(
                ok=False,
                content="rendered mode requires playwright/chromium (full variant)",
                duration_ms=_ms(start),
            )
        import trafilatura

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    executable_path=_chromium_path(), args=["--no-sandbox"]
                )
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60000)
                html = await page.content()
                await browser.close()
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                ok=False, content=f"rendered fetch failed: {e}", duration_ms=_ms(start)
            )
        extracted = trafilatura.extract(html, output_format="markdown") or html
        return ToolResult(
            ok=True, content=extracted[:MAX_FETCH_BYTES], duration_ms=_ms(start)
        )


register(WebSearchTool())
register(WebFetchTool())
