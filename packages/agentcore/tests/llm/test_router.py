import pytest

from agentcore.llm.anthropic import AnthropicClient
from agentcore.llm.openai_compat import OpenAICompatClient
from agentcore.llm.router import LLMRouter

pytestmark = pytest.mark.unit


def test_claude_routes_to_anthropic_native():
    client, wire = LLMRouter().route("claude-opus-4-7")
    assert isinstance(client, AnthropicClient)
    assert wire == "claude-opus-4-7"
    assert client._base_url == "https://api.anthropic.com"


@pytest.mark.parametrize("model", ["gpt-5.2", "gpt-4o-mini", "o3-mini", "o4-mini"])
def test_openai_prefixes_route_to_native_openai(model):
    client, wire = LLMRouter().route(model)
    assert isinstance(client, OpenAICompatClient)
    assert wire == model
    assert client._base_url == "https://api.openai.com/v1"
    # Native OpenAI needs max_completion_tokens.
    assert client._use_max_completion_tokens is True


@pytest.mark.parametrize("model,family_anthropic", [
    ("opencode-go/minimax-m3", True),
    ("opencode-go/qwen3.7-max", True),
    ("opencode-go/deepseek-v4-pro", False),
    ("opencode-go/glm-5.2", False),
    ("opencode-go/kimi-k2.7-code", False),
    ("opencode-go/mimo-v2.5", False),
])
def test_opencode_go_family_split(model, family_anthropic):
    client, wire = LLMRouter().route(model)
    assert wire == model.split("/", 1)[1]  # prefix stripped
    if family_anthropic:
        assert isinstance(client, AnthropicClient)
        assert client._base_url == "https://opencode.ai/zen/go"
    else:
        assert isinstance(client, OpenAICompatClient)
        assert client._base_url == "https://opencode.ai/zen/go/v1"
        # Gateways expect max_tokens, not max_completion_tokens.
        assert client._use_max_completion_tokens is False


def test_base_url_overrides_flow_to_clients():
    r = LLMRouter(
        anthropic_base_url="http://stub:1",
        openai_base_url="http://stub:2/v1",
        opencode_go_base_url="http://stub:3",
    )
    assert r.route("claude-x")[0]._base_url == "http://stub:1"
    assert r.route("gpt-x")[0]._base_url == "http://stub:2/v1"
    assert r.route("opencode-go/qwen3.7-max")[0]._base_url == "http://stub:3"
    assert r.route("opencode-go/glm-5.2")[0]._base_url == "http://stub:3/v1"


def test_unroutable_model_raises_value_error():
    with pytest.raises(ValueError, match="no LLM route"):
        LLMRouter().route("gemini-3.5-flash")
    with pytest.raises(ValueError, match="no LLM route"):
        LLMRouter().route("opencode/deepseek-v4-flash-free")  # Zen ≠ Go
