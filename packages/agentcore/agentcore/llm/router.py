"""Model → LLM client routing for the vanilla driver.

One router instance owns one client per (protocol, backend) pair and maps a
catalog model id to (client, wire model id). Base URLs are constructor args so
the shim can override them from env for stubs/tests.

URL conventions: AnthropicClient appends ``/v1/messages`` to its base (Zen Go
base therefore has no ``/v1``); OpenAICompatClient appends ``/chat/completions``
(its bases include the version segment).
"""
from __future__ import annotations

from agentcore.llm.anthropic import DEFAULT_BASE_URL as ANTHROPIC_DEFAULT_BASE_URL
from agentcore.llm.anthropic import AnthropicClient
from agentcore.llm.base import LLMClient
from agentcore.llm.openai_compat import DEFAULT_BASE_URL as OPENAI_DEFAULT_BASE_URL
from agentcore.llm.openai_compat import OpenAICompatClient

OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go"

# Bare model-id prefixes that resolve to the native OpenAI API. The control
# plane's credentials_service builds its provider table from this tuple so
# routing and credential resolution cannot drift.
OPENAI_MODEL_PREFIXES: tuple[str, ...] = ("gpt", "o1", "o3", "o4", "o5")

# opencode Go families served by Zen's anthropic-compatible /messages endpoint;
# every other Go family speaks chat-completions. Sourced from the Zen docs —
# the gateway's /models endpoint exposes no protocol field.
GO_ANTHROPIC_FAMILIES: tuple[str, ...] = ("minimax", "qwen")

_GO_PREFIX = "opencode-go/"


class LLMRouter:
    def __init__(
        self,
        *,
        anthropic_base_url: str = ANTHROPIC_DEFAULT_BASE_URL,
        openai_base_url: str = OPENAI_DEFAULT_BASE_URL,
        opencode_go_base_url: str = OPENCODE_GO_DEFAULT_BASE_URL,
    ) -> None:
        self._anthropic = AnthropicClient(base_url=anthropic_base_url)
        self._openai = OpenAICompatClient(
            base_url=openai_base_url, use_max_completion_tokens=True
        )
        self._go_anthropic = AnthropicClient(base_url=opencode_go_base_url)
        self._go_openai = OpenAICompatClient(
            base_url=f"{opencode_go_base_url.rstrip('/')}/v1"
        )

    def route(self, model: str) -> tuple[LLMClient, str]:
        """Return (client, wire model id) for a catalog model id.

        Raises ValueError for ids no table matches — config validation blocks
        these at submit time, so this is a defense-in-depth guard.
        """
        if model.startswith(_GO_PREFIX):
            name = model[len(_GO_PREFIX):]
            if name.startswith(GO_ANTHROPIC_FAMILIES):
                return self._go_anthropic, name
            return self._go_openai, name
        if model.startswith("claude"):
            return self._anthropic, model
        if model.startswith(OPENAI_MODEL_PREFIXES):
            return self._openai, model
        raise ValueError(f"no LLM route for model {model!r}")
