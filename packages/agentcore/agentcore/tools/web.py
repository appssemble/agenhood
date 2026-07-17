from __future__ import annotations

import os
import re
import shutil
import time
from typing import Any

import httpx

from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms, register
from agentcore.tools.exa import ExaError, exa_api_key, exa_search

DEFAULT_SEARCH_URL = "http://searxng:8080"
MAX_FETCH_BYTES = 5 * 1024 * 1024  # 5 MiB
SEARCH_RESULT_LIMIT = 8
WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _unresponsive_engines(data: dict[str, Any]) -> list[str]:
    """Format SearXNG's ``unresponsive_engines`` pairs; [] on anything odd."""
    raw = data.get("unresponsive_engines")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for entry in raw:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            out.append(f"{entry[0]} ({entry[1]})")
        elif isinstance(entry, str):
            out.append(entry)
    return out


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
        query = input["query"]
        key = exa_api_key(ctx)
        if not key:
            return await self._searxng_search(query, start)
        try:
            results = await exa_search(query, key, limit=SEARCH_RESULT_LIMIT)
        except ExaError as e:
            fallback = await self._searxng_search(query, start)
            return ToolResult(
                ok=fallback.ok,
                content=(
                    f"note: primary search (exa) failed — {e}; "
                    "results from fallback search:\n" + fallback.content
                ),
                duration_ms=fallback.duration_ms,
            )
        lines = [
            f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
            for i, r in enumerate(results, 1)
        ]
        return ToolResult(ok=True, content="\n".join(lines), duration_ms=_ms(start))

    async def _searxng_search(self, query: str, start: float) -> ToolResult:
        base = os.environ.get("SEARCH_PROVIDER_URL", DEFAULT_SEARCH_URL).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.get(
                    f"{base}/search",
                    params={"q": query, "format": "json"},
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001 — surface network/parse errors to the model
            return await self._wikipedia_floor_or_error(
                query, f"search failed: {e}", f"search failed: {e}", start
            )

        results = data.get("results", [])[:SEARCH_RESULT_LIMIT]
        if not results:
            # SearXNG answers 200 with an empty list even when every upstream
            # engine is CAPTCHA'd/rate-limited; `unresponsive_engines` is the
            # only signal. Surface that as a failure so the model (and the
            # loop's failure breaker) can tell "backend down" from "no hits".
            engines = _unresponsive_engines(data)
            if engines:
                reason = "engines unresponsive: " + ", ".join(engines)
                return await self._wikipedia_floor_or_error(
                    query,
                    reason,
                    "search backend degraded — "
                    + reason
                    + "; retrying the same search will not help",
                    start,
                )
            return ToolResult(ok=True, content="(no results)", duration_ms=_ms(start))
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        return ToolResult(ok=True, content="\n".join(lines), duration_ms=_ms(start))

    async def _wikipedia_floor_or_error(
        self, query: str, reason: str, error_msg: str, start: float
    ) -> ToolResult:
        """SearXNG gave nothing usable — try the keyless Wikipedia search API.

        Wikipedia is the only truly free source that never bot-blocks us, but
        it only covers encyclopedic queries, so label the response honestly.
        On any fallback failure, surface the original error unchanged so the
        loop's failure breaker still sees the streak.
        """
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                # Wikimedia 403s default library User-Agents (API etiquette
                # requires a descriptive one with a contact URL).
                headers={
                    "User-Agent": (
                        "agenhood-web-search/1.0 "
                        "(https://github.com/appssemble/agenhood-public)"
                    )
                },
            ) as http:
                resp = await http.get(
                    WIKIPEDIA_SEARCH_URL,
                    params={"q": query, "limit": str(SEARCH_RESULT_LIMIT)},
                )
            resp.raise_for_status()
            pages = resp.json().get("pages") or []
        except Exception:  # noqa: BLE001 — fallback is best-effort
            pages = []
        lines = []
        for i, p in enumerate(pages[:SEARCH_RESULT_LIMIT], 1):
            if not isinstance(p, dict):
                continue
            title = p.get("title", "")
            key = p.get("key", "")
            url = f"https://en.wikipedia.org/wiki/{key}" if key else ""
            snippet = _HTML_TAG_RE.sub("", p.get("excerpt") or p.get("description") or "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        if not lines:
            return ToolResult(ok=False, content=error_msg, duration_ms=_ms(start))
        return ToolResult(
            ok=True,
            content=(
                f"web search degraded ({reason}); showing Wikipedia-only results — "
                "non-encyclopedic queries may be poorly served:\n" + "\n".join(lines)
            ),
            duration_ms=_ms(start),
        )


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
        try:
            url = input["url"]
        except KeyError:
            return ToolResult(
                ok=False, content="missing required field: url", duration_ms=_ms(start)
            )
        mode = input.get("mode", "text")
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
        content = extracted[:MAX_FETCH_BYTES]
        if len(extracted) > MAX_FETCH_BYTES:
            content += "\n[...response truncated at 5 MiB...]"
        return ToolResult(ok=True, content=content, duration_ms=_ms(start))


register(WebSearchTool())
register(WebFetchTool())
