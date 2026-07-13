"""The /v1/credentials/providers dropdown source: opencode-go catalog entries
must surface as the single storable provider id "opencode"."""
from __future__ import annotations

import pytest

from control_plane.model_catalog import ModelEntry
from control_plane.routers.credentials import _KNOWN_PROVIDERS, _PROVIDER_LABELS

pytestmark = pytest.mark.unit


def test_opencode_is_a_known_api_key_provider() -> None:
    assert "opencode" in _KNOWN_PROVIDERS
    assert _PROVIDER_LABELS["opencode"] == "OpenCode (Zen / Go)"


def test_providers_endpoint_dedupes_opencode_go(monkeypatch) -> None:
    # Build the provider set the same way the endpoint does, from a catalog
    # containing both opencode-go (Go) and opencode (paid Zen) api_key entries.
    from control_plane.credentials_service import credential_provider_for

    catalog = [
        ModelEntry(
            id="opencode-go/glm-5.2", provider="opencode-go", label="glm-5.2",
            category="api_key", credentials=("opencode_api_key",), drivers=("opencode",),
        ),
        ModelEntry(
            id="opencode/kimi-k2", provider="opencode", label="kimi-k2",
            category="api_key", credentials=("opencode_api_key",), drivers=("opencode",),
        ),
        ModelEntry(
            id="opencode/deepseek-v4-flash-free", provider="opencode",
            label="deepseek-v4-flash-free", category="free",
            credentials=("keyless",), drivers=("opencode",),
        ),
    ]
    providers = sorted({
        credential_provider_for(e.provider) for e in catalog if e.category == "api_key"
    })
    assert providers == ["opencode"]
