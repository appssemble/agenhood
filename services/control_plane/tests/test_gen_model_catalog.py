from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import json  # noqa: E402

from gen_model_catalog import parse_codex_models, parse_model_ids  # noqa: E402


def test_parse_codex_models_keeps_listed_drops_hidden() -> None:
    # Shape of `codex debug models` stdout: {"models": [{slug, visibility, ...}]}.
    text = json.dumps({
        "models": [
            {"slug": "gpt-5.5", "visibility": "list", "supported_in_api": True},
            {"slug": "gpt-5.3-codex-spark", "visibility": "list", "supported_in_api": False},
            {"slug": "codex-auto-review", "visibility": "hide", "supported_in_api": True},
        ]
    })
    assert parse_codex_models(text) == ["gpt-5.5", "gpt-5.3-codex-spark"]


def test_parse_codex_models_accepts_bare_list() -> None:
    text = json.dumps([{"slug": "gpt-5.4", "visibility": "list"}])
    assert parse_codex_models(text) == ["gpt-5.4"]


def test_parse_model_ids_filters_provider_lines() -> None:
    text = """
loading...
opencode/deepseek-v4-flash-free
anthropic/claude-opus-4-8
openai/gpt-5.4
not a model line
INFO something
""".strip()
    assert parse_model_ids(text) == [
        "opencode/deepseek-v4-flash-free",
        "anthropic/claude-opus-4-8",
        "openai/gpt-5.4",
    ]


def test_placeholder_go_auth_configures_opencode_providers() -> None:
    from gen_model_catalog import _PLACEHOLDER_AUTH, _PLACEHOLDER_GO_AUTH

    # The go run must keep the base placeholders AND configure both opencode
    # provider ids so `opencode models` lists opencode-go/* (and paid Zen).
    for provider, entry in _PLACEHOLDER_AUTH.items():
        assert _PLACEHOLDER_GO_AUTH[provider] == entry
    for provider in ("opencode", "opencode-go"):
        assert _PLACEHOLDER_GO_AUTH[provider]["type"] == "api"
        assert _PLACEHOLDER_GO_AUTH[provider]["key"]
