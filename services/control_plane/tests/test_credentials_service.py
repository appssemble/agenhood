from __future__ import annotations

import os

import pytest

from control_plane.credentials_service import (
    build_credential_row,
    credential_provider_for,
    decrypt_row,
    last4,
    model_is_keyless,
    provider_for_model,
    provider_is_keyless,
)


@pytest.fixture
def key() -> bytes:
    return os.urandom(32)


def test_provider_for_model_maps_anthropic() -> None:
    assert provider_for_model("claude-opus-4-7") == "anthropic"
    assert provider_for_model("claude-sonnet-4-6") == "anthropic"


def test_provider_for_model_maps_claude_code_aliases() -> None:
    # claude-code's model catalog offers only the bare family aliases (see
    # model_catalog._CLAUDE_CODE_ALIASES) — none start with "claude", so they
    # need their own mapping alongside the prefix table.
    assert provider_for_model("opus") == "anthropic"
    assert provider_for_model("sonnet") == "anthropic"
    assert provider_for_model("haiku") == "anthropic"
    assert provider_for_model("Opus") == "anthropic"  # case-insensitive, like the rest


def test_provider_for_model_maps_openai() -> None:
    assert provider_for_model("gpt-4o") == "openai"


def test_provider_for_model_unknown_raises() -> None:
    with pytest.raises(ValueError):
        provider_for_model("mystery-model-9000")


def test_provider_for_model_qualified_id_uses_prefix() -> None:
    # A fully-qualified provider/model id (opencode free models) resolves to
    # its prefix provider, not the bare-id prefix table.
    assert provider_for_model("opencode/deepseek-v4-flash-free") == "opencode"
    assert provider_for_model("anthropic/claude-sonnet-4-6") == "anthropic"
    assert provider_for_model("openai/gpt-4o") == "openai"


def test_provider_is_keyless() -> None:
    assert provider_is_keyless("opencode") is True
    assert provider_is_keyless("anthropic") is False
    assert provider_is_keyless("openai") is False


def test_last4() -> None:
    assert last4("sk-ant-abcd1234") == "1234"


def test_build_row_encrypts_and_stores_last4(key: bytes) -> None:
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key="sk-ant-supersecret-7890",
        created_by="usr_1",
        master_key=key,
    )
    assert row["provider"] == "anthropic"
    assert row["key_last4"] == "7890"
    assert b"supersecret" not in row["key_ciphertext"]
    assert decrypt_row(row, key) == "sk-ant-supersecret-7890"


def test_decrypt_row_round_trip(key: bytes) -> None:
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key="sk-ant-xyz",
        created_by=None,
        master_key=key,
    )
    assert decrypt_row(row, key) == "sk-ant-xyz"


def test_provider_for_model_opencode_go_prefix() -> None:
    assert provider_for_model("opencode-go/glm-5.2") == "opencode-go"
    assert provider_for_model("opencode-go/kimi-k2.7-code") == "opencode-go"


def test_credential_provider_for_aliases_opencode_go() -> None:
    # opencode-go models are unlocked by the single "opencode" credential row.
    assert credential_provider_for("opencode-go") == "opencode"
    assert credential_provider_for("opencode") == "opencode"
    assert credential_provider_for("anthropic") == "anthropic"


def test_model_is_keyless_only_for_free_zen() -> None:
    assert model_is_keyless("opencode/deepseek-v4-flash-free") is True
    # Paid Zen and Go models need the opencode key.
    assert model_is_keyless("opencode/kimi-k2") is False
    assert model_is_keyless("opencode-go/glm-5.2") is False
    # Other providers are never keyless.
    assert model_is_keyless("claude-opus-4-7") is False
    assert model_is_keyless("openai/gpt-4o") is False
