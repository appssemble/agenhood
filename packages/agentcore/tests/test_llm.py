import asyncio

from agentcore.llm.base import LLMClient, LLMResponse


class _FakeLLM:
    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        credential: str,
    ) -> LLMResponse:
        return LLMResponse(
            content=[{"type": "text", "text": f"{model}:{len(messages)}"}],
            tokens_in=len(system),
            tokens_out=max_tokens,
            stop_reason="end_turn",
        )


def test_fake_satisfies_protocol_and_returns_response():
    client: LLMClient = _FakeLLM()

    async def go() -> LLMResponse:
        return await client.create(
            model="claude-opus-4-7",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            max_tokens=4096,
            credential="cred",
        )

    resp = asyncio.run(go())
    assert resp.content == [{"type": "text", "text": "claude-opus-4-7:1"}]
    assert resp.tokens_in == 3
    assert resp.tokens_out == 4096
    assert resp.stop_reason == "end_turn"
