from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from control_plane.model_catalog import build_catalog_entries, methods_from_credential_rows


def test_classifies_free_anthropic_openai_subscription() -> None:
    base = ["opencode/deepseek-v4-flash-free", "anthropic/claude-opus-4-8", "openai/gpt-4o"]
    sub = ["openai/gpt-5.3-codex-spark", "openai/gpt-4o"]  # gpt-4o in both
    entries = {e["id"]: e for e in build_catalog_entries(base, sub)}

    zen = entries["opencode/deepseek-v4-flash-free"]
    assert zen["category"] == "free"
    assert zen["credentials"] == ["keyless"]
    assert zen["drivers"] == ["opencode"]

    ant = entries["claude-opus-4-8"]
    assert ant["category"] == "api_key"
    assert ant["credentials"] == ["anthropic_api_key", "anthropic_subscription"]
    # Full-name anthropic models never offer claude-code (alias-only; see below).
    assert ant["drivers"] == ["opencode", "vanilla"]

    # openai in BOTH base and sub → api_key category, both credential methods.
    # gpt-4o is NOT a Codex-tuned model, so codex is filtered out of its drivers.
    gpt4o = entries["gpt-4o"]
    assert gpt4o["category"] == "api_key"
    assert set(gpt4o["credentials"]) == {"openai_api_key", "openai_subscription"}
    assert gpt4o["drivers"] == ["opencode", "vanilla"]

    # openai only in sub → subscription. A *-codex* model keeps the codex driver.
    codex = entries["gpt-5.3-codex-spark"]
    assert codex["category"] == "subscription"
    assert codex["credentials"] == ["openai_subscription"]
    assert codex["drivers"] == ["opencode", "codex"]


def test_label_is_derived_from_id() -> None:
    entries = {e["id"]: e for e in build_catalog_entries(["openai/gpt-5.4"], [])}
    assert entries["gpt-5.4"]["label"] == "gpt-5.4"


def test_unknown_provider_ignored() -> None:
    # Providers we don't support (no credential method) are dropped.
    ids = [e["id"] for e in build_catalog_entries(["mystery/foo-1", "anthropic/claude-opus-4-8"], [])]
    assert "claude-opus-4-8" in ids
    assert "foo-1" not in ids and "mystery/foo-1" not in ids


def test_non_chat_models_excluded() -> None:
    base = [
        "openai/gpt-4o",
        "openai/text-embedding-3-large",
        "openai/chatgpt-image-latest",
        "openai/dall-e-3",
        "openai/whisper-1",
        "openai/tts-1",
        "openai/omni-moderation-latest",
        "openai/gpt-4o-realtime-preview",
        "anthropic/claude-opus-4-8",
    ]
    # The classifier also appends the three claude-code alias entries.
    ids = {e["id"] for e in build_catalog_entries(base, [])}
    assert {"gpt-4o", "claude-opus-4-8"} <= ids
    assert ids - {"opus", "sonnet", "haiku"} == {"gpt-4o", "claude-opus-4-8"}


def test_full_name_anthropic_does_not_offer_claude_code():
    from control_plane.model_catalog import build_catalog_entries

    entries = build_catalog_entries(["anthropic/claude-opus-4-8"], [], None)
    entry = next(e for e in entries if e["id"] == "claude-opus-4-8")
    assert "claude-code" not in entry["drivers"]
    assert "vanilla" in entry["drivers"]
    assert entry["credentials"] == ["anthropic_api_key", "anthropic_subscription"]


def test_claude_code_offered_only_via_family_aliases():
    from control_plane.model_catalog import build_catalog_entries

    entries = build_catalog_entries(["anthropic/claude-opus-4-8"], [], None)
    aliases = {e["id"]: e for e in entries if e["drivers"] == ["claude-code"]}
    assert set(aliases) == {"opus", "sonnet", "haiku"}
    for e in aliases.values():
        assert e["provider"] == "anthropic"
        assert e["credentials"] == ["anthropic_api_key", "anthropic_subscription"]


def test_methods_includes_anthropic_subscription():
    from control_plane.model_catalog import methods_from_credential_rows

    rows = [{"provider": "anthropic", "auth_method": "oauth_subscription", "status": "active"}]
    assert "anthropic_subscription" in methods_from_credential_rows(rows)


def test_methods_excludes_inactive_anthropic_subscription():
    from control_plane.model_catalog import methods_from_credential_rows
    rows = [{"provider": "anthropic", "auth_method": "oauth_subscription", "status": "inactive"}]
    assert "anthropic_subscription" not in methods_from_credential_rows(rows)


def test_go_ids_classified_as_opencode_api_key() -> None:
    entries = build_catalog_entries(
        [], [], go_ids=["opencode-go/glm-5.2", "opencode-go/kimi-k2.7-code"]
    )
    go = [e for e in entries if e["provider"] == "opencode-go"]
    assert {e["id"] for e in go} == {"opencode-go/glm-5.2", "opencode-go/kimi-k2.7-code"}
    for e in go:
        assert e["category"] == "api_key"
        assert e["credentials"] == ["opencode_api_key"]
        assert e["drivers"] == ["opencode", "vanilla"]


def test_paid_zen_requires_opencode_key_free_zen_stays_keyless() -> None:
    entries = build_catalog_entries(
        ["opencode/deepseek-v4-flash-free", "opencode/kimi-k2"], []
    )
    by_id = {e["id"]: e for e in entries}
    free = by_id["opencode/deepseek-v4-flash-free"]
    assert free["category"] == "free"
    assert free["credentials"] == ["keyless"]
    paid = by_id["opencode/kimi-k2"]
    assert paid["category"] == "api_key"
    assert paid["credentials"] == ["opencode_api_key"]
    assert paid["drivers"] == ["opencode"]


def test_go_ids_duplicated_in_base_are_not_double_counted() -> None:
    # The go run re-lists everything the base run lists; dedupe by entry id.
    entries = build_catalog_entries(
        ["opencode/deepseek-v4-flash-free"],
        [],
        go_ids=["opencode/deepseek-v4-flash-free", "opencode-go/glm-5.2"],
    )
    ids = [e["id"] for e in entries if e["provider"] in ("opencode", "opencode-go")]
    assert ids.count("opencode/deepseek-v4-flash-free") == 1
    assert "opencode-go/glm-5.2" in ids


def test_methods_includes_opencode_api_key() -> None:
    rows = [{"provider": "opencode", "auth_method": "api_key"}]
    assert "opencode_api_key" in methods_from_credential_rows(rows)


def test_openai_api_key_models_gain_vanilla():
    entries = build_catalog_entries(["openai/gpt-5.2"], [])
    e = next(m for m in entries if m["id"] == "gpt-5.2")
    assert "vanilla" in e["drivers"]
    assert "opencode" in e["drivers"]


def test_openai_codex_family_excluded_from_vanilla():
    entries = build_catalog_entries(["openai/gpt-5.2-codex"], [])
    e = next(m for m in entries if m["id"] == "gpt-5.2-codex")
    assert "vanilla" not in e["drivers"]


def test_openai_subscription_only_models_excluded_from_vanilla():
    # In sub_ids only (not base) -> subscription-only -> no API key for vanilla.
    entries = build_catalog_entries([], ["openai/gpt-6-preview"])
    e = next(m for m in entries if m["id"] == "gpt-6-preview")
    assert e["category"] == "subscription"
    assert "vanilla" not in e["drivers"]


def test_opencode_go_models_gain_vanilla():
    entries = build_catalog_entries([], [], go_ids=["opencode-go/glm-5.2",
                                                    "opencode-go/qwen3.7-max"])
    for mid in ("opencode-go/glm-5.2", "opencode-go/qwen3.7-max"):
        e = next(m for m in entries if m["id"] == mid)
        assert e["drivers"] == ["opencode", "vanilla"]
        assert e["credentials"] == ["opencode_api_key"]


def test_paid_zen_models_do_not_gain_vanilla():
    entries = build_catalog_entries(["opencode/grok-code-4"], [])
    e = next(m for m in entries if m["id"] == "opencode/grok-code-4")
    assert e["drivers"] == ["opencode"]


def test_vanilla_subscription_support_stays_empty():
    from control_plane.model_catalog import driver_can_use_subscription
    assert not driver_can_use_subscription("vanilla", "openai")
    assert not driver_can_use_subscription("vanilla", "anthropic")
