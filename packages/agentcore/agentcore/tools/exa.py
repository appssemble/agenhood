"""Thin async client for the Exa AI REST API (search + contents).

Used by tools/web.py as the primary hosted provider. Deliberately minimal:
two functions and one error type — no provider framework. Raises ``ExaError``
on any failure so callers can fall back to the free paths.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from agentcore.tools.base import ToolContext

EXA_BASE_URL = "https://api.exa.ai"
SEARCH_TIMEOUT = 15.0
CONTENTS_TIMEOUT = 30.0
_SNIPPET_FALLBACK_CHARS = 300


class ExaError(Exception):
    """Any Exa failure: HTTP >= 400, network/timeout, or unusable payload."""


def exa_api_key(ctx: ToolContext) -> str:
    """Resolve the key: per-container env first, then process env; '' = absent."""
    return (ctx.env.get("EXA_API_KEY") or os.environ.get("EXA_API_KEY") or "").strip()


async def _post(
    path: str, payload: dict[str, Any], api_key: str, http_timeout: float
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=http_timeout) as http:
            resp = await http.post(
                f"{EXA_BASE_URL}{path}", json=payload, headers={"x-api-key": api_key}
            )
    except Exception as e:  # noqa: BLE001 — every transport failure becomes ExaError
        raise ExaError(f"request failed: {e}") from e
    if resp.status_code >= 400:
        raise ExaError(f"http {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as e:
        raise ExaError("unparseable response") from e
    if not isinstance(data, dict):
        raise ExaError("unparseable response")
    return data


async def exa_search(
    query: str, api_key: str, *, limit: int = 8
) -> list[dict[str, str]]:
    data = await _post(
        "/search",
        {
            "query": query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": True},
        },
        api_key,
        SEARCH_TIMEOUT,
    )
    raw = data.get("results")
    out: list[dict[str, str]] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        highlights = r.get("highlights")
        if isinstance(highlights, list) and highlights:
            snippet = " ".join(str(h) for h in highlights)
        else:
            snippet = str(r.get("text") or "")[:_SNIPPET_FALLBACK_CHARS]
        out.append(
            {
                "title": str(r.get("title") or ""),
                "url": str(r.get("url") or ""),
                "snippet": snippet,
            }
        )
    if not out:
        raise ExaError("no results in response")
    return out


async def exa_contents(url: str, api_key: str) -> str:
    data = await _post(
        "/contents", {"urls": [url], "text": True}, api_key, CONTENTS_TIMEOUT
    )
    raw = data.get("results")
    first = raw[0] if isinstance(raw, list) and raw else None
    text = first.get("text") if isinstance(first, dict) else None
    if not text:
        raise ExaError("no content in response")
    return str(text)
