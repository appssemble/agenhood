from __future__ import annotations

import json

from control_plane.model_catalog import ModelEntry, is_valid, load_catalog


def _write(tmp_path, entries):
    p = tmp_path / "cat.json"
    p.write_text(json.dumps({"models": entries}))
    return p


def test_load_and_is_valid(tmp_path) -> None:
    p = _write(tmp_path, [
        {
            "id": "claude-opus-4-8", "provider": "anthropic",
            "label": "claude-opus-4-8", "category": "api_key",
            "credentials": ["anthropic_api_key"], "drivers": ["opencode", "vanilla"],
        },
        {
            "id": "gpt-5.4", "provider": "openai", "label": "gpt-5.4",
            "category": "api_key", "credentials": ["openai_api_key"], "drivers": ["opencode"],
        },
    ])
    cat = load_catalog(p)
    assert all(isinstance(e, ModelEntry) for e in cat)
    assert is_valid(cat, "claude-opus-4-8", "vanilla") is True
    assert is_valid(cat, "claude-opus-4-8", "opencode") is True
    assert is_valid(cat, "gpt-5.4", "vanilla") is False        # vanilla can't run openai
    assert is_valid(cat, "nope", "opencode") is False          # unknown model


def test_missing_file_loads_empty_and_is_valid_skips(tmp_path) -> None:
    cat = load_catalog(tmp_path / "does-not-exist.json")
    assert cat == []
    # Graceful: with no catalog, is_valid returns True (skip) so submits don't hard-fail.
    assert is_valid(cat, "anything", "opencode") is True
