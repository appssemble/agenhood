from __future__ import annotations

from control_plane.model_catalog import ModelEntry, annotate, methods_from_credential_rows


def _cat():
    return [
        ModelEntry(
            "opencode/zen-free", "opencode", "zen-free", "free", ("keyless",), ("opencode",)
        ),
        ModelEntry("claude-opus-4-8", "anthropic", "claude-opus-4-8", "api_key",
                   ("anthropic_api_key",), ("opencode", "vanilla")),
        ModelEntry("gpt-5.4", "openai", "gpt-5.4", "api_key",
                   ("openai_api_key", "openai_subscription"), ("opencode",)),
        ModelEntry("gpt-5.3-codex-spark", "openai", "gpt-5.3-codex-spark", "subscription",
                   ("openai_subscription",), ("opencode",)),
    ]


def test_methods_from_rows() -> None:
    rows = [
        {"provider": "anthropic", "auth_method": "api_key", "status": "active"},
        {"provider": "openai", "auth_method": "oauth_subscription", "status": "active"},
        # reauth_required → ignored
        {"provider": "openai", "auth_method": "oauth_subscription", "status": "reauth_required"},
    ]
    assert methods_from_credential_rows(rows) == {
        "keyless", "anthropic_api_key", "openai_subscription"
    }


def test_annotate_no_credentials_only_free_usable() -> None:
    out = {m["id"]: m for m in annotate(_cat(), "opencode", {"keyless"})}
    assert out["opencode/zen-free"]["available"] is True
    assert out["claude-opus-4-8"]["available"] is False
    assert out["claude-opus-4-8"]["requires"] == ["anthropic_api_key"]
    assert out["gpt-5.3-codex-spark"]["requires"] == ["openai_subscription"]


def test_annotate_driver_filter_vanilla_only_anthropic() -> None:
    ids = [m["id"] for m in annotate(_cat(), "vanilla", {"keyless"})]
    assert ids == ["claude-opus-4-8"]


def test_annotate_subscription_makes_codex_usable() -> None:
    out = {m["id"]: m for m in annotate(_cat(), "opencode", {"keyless", "openai_subscription"})}
    assert out["gpt-5.3-codex-spark"]["available"] is True
    assert out["gpt-5.4"]["available"] is True  # satisfied by openai_subscription


def _cat_anthropic_dual():
    # Anthropic model runnable via API key OR subscription (the real catalog shape).
    return [
        ModelEntry(
            "claude-opus-4-8", "anthropic", "claude-opus-4-8", "api_key",
            ("anthropic_api_key", "anthropic_subscription"), ("opencode", "vanilla"),
        ),
        ModelEntry(
            "opus", "anthropic", "opus", "api_key",
            ("anthropic_api_key", "anthropic_subscription"), ("claude-code",),
        ),
    ]


def test_anthropic_subscription_not_usable_on_opencode() -> None:
    # opencode cannot consume an anthropic subscription, so with only a
    # subscription the anthropic model is unavailable and asks for an API key.
    out = {m["id"]: m for m in annotate(_cat_anthropic_dual(), "opencode",
                                        {"keyless", "anthropic_subscription"})}
    assert out["claude-opus-4-8"]["available"] is False
    assert out["claude-opus-4-8"]["requires"] == ["anthropic_api_key"]


def test_anthropic_subscription_not_usable_on_vanilla() -> None:
    out = {m["id"]: m for m in annotate(_cat_anthropic_dual(), "vanilla",
                                        {"keyless", "anthropic_subscription"})}
    assert out["claude-opus-4-8"]["available"] is False
    assert out["claude-opus-4-8"]["requires"] == ["anthropic_api_key"]


def test_anthropic_subscription_usable_on_claude_code() -> None:
    # claude-code is the driver built around the anthropic subscription.
    out = {m["id"]: m for m in annotate(_cat_anthropic_dual(), "claude-code",
                                        {"keyless", "anthropic_subscription"})}
    assert out["opus"]["available"] is True


def test_anthropic_api_key_still_usable_on_opencode() -> None:
    out = {m["id"]: m for m in annotate(_cat_anthropic_dual(), "opencode",
                                        {"keyless", "anthropic_api_key"})}
    assert out["claude-opus-4-8"]["available"] is True


def test_go_model_available_only_with_opencode_key() -> None:
    entry = ModelEntry(
        id="opencode-go/glm-5.2", provider="opencode-go", label="glm-5.2",
        category="api_key", credentials=("opencode_api_key",), drivers=("opencode",),
    )
    without = annotate([entry], "opencode", {"keyless"})
    assert without[0]["available"] is False
    assert without[0]["requires"] == ["opencode_api_key"]
    with_key = annotate([entry], "opencode", {"keyless", "opencode_api_key"})
    assert with_key[0]["available"] is True
