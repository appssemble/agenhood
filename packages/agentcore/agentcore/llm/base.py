"""Provider-agnostic LLM client Protocol and response type (index §5).

The vanilla driver (Unit 1) and the control plane type against this. The
Anthropic Messages adapter that satisfies it lives in ``agentcore/llm/anthropic.py``
(Unit 1). ``content`` is an Anthropic-style content-block array.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    content: list[dict[str, Any]]  # Anthropic-style content blocks
    tokens_in: int
    tokens_out: int
    stop_reason: str


class LLMClient(Protocol):
    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        credential: str,
    ) -> LLMResponse: ...
