"""The /v1/credentials/providers dropdown source: opencode-go catalog entries
must surface as the single storable provider id "opencode"."""
from __future__ import annotations

import types

import pytest

from control_plane.auth.principal import Principal
from control_plane.model_catalog import ModelEntry
from control_plane.routers.credentials import (
    _KNOWN_PROVIDERS,
    _PROVIDER_LABELS,
    list_api_key_providers,
)

pytestmark = pytest.mark.unit


def test_opencode_is_a_known_api_key_provider() -> None:
    assert "opencode" in _KNOWN_PROVIDERS
    assert _PROVIDER_LABELS["opencode"] == "OpenCode (Zen / Go)"


async def test_providers_endpoint_dedupes_opencode_go() -> None:
    # Catalog containing both opencode-go (Go) and opencode (paid Zen)
    # api_key entries, plus a free entry that must not appear at all.
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
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(model_catalog=catalog))
    )
    principal = Principal(tenant_id="t1", role="admin", is_staff=False, user_id="u1")

    result = await list_api_key_providers(request, p=principal)  # type: ignore[arg-type]

    assert result == {"providers": [{"id": "opencode", "label": "OpenCode (Zen / Go)"}]}
