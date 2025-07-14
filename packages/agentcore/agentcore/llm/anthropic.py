from __future__ import annotations

from typing import Any

import httpx

from agentcore.llm.base import LLMResponse

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicClient:
    """LLMClient implementation targeting Anthropic's Messages API over httpx.

    base_url is configurable so unit tests can point at a respx stub and
    integration tests at the local stub-LLM service.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        credential: str,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "system": system,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "x-api-key": credential,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(
                f"{self._base_url}/v1/messages", json=payload, headers=headers
            )
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("error", {}).get("message", resp.text)
            except Exception:  # noqa: BLE001 — non-JSON error body
                message = resp.text
            raise RuntimeError(f"anthropic api error {resp.status_code}: {message}")

        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            content=data["content"],
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            stop_reason=data.get("stop_reason", ""),
        )
