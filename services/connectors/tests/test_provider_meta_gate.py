from __future__ import annotations

import importlib
import pkgutil

import pytest

import connectors.providers as providers_pkg
from connectors.app import create_app

pytestmark = pytest.mark.unit


def discover_providers() -> dict[str, type]:
    """Every concrete provider class in connectors.providers (excluding base)."""
    found: dict[str, type] = {}
    for mod in pkgutil.iter_modules(providers_pkg.__path__):
        if mod.name == "base":
            continue
        m = importlib.import_module(f"connectors.providers.{mod.name}")
        for obj in vars(m).values():
            if (isinstance(obj, type)
                    and getattr(obj, "__module__", "") == m.__name__
                    and isinstance(getattr(obj, "name", None), str)
                    and hasattr(obj, "verify_webhook")):
                found[obj.name] = obj
    return found


# Each provider MUST cite an inbound (webhook→routing→delivery), an outbound
# (post/update), and a tenant-isolation test. A new provider with no entry
# fails test_every_provider_has_inbound_outbound_isolation below.
PROVIDER_COVERAGE: dict[str, dict[str, str]] = {
    "slack": {
        "inbound": "test_webhooks_router::test_webhook_slack_triggers_delivery",
        "outbound": "test_slack_provider::test_post_initial_returns_handle",
        "isolation": (
            "test_orchestrator_tenant_isolation::"
            "test_event_from_different_workspace_is_not_routed"
        ),
    },
    "github": {
        "inbound": "test_github_inbound::test_github_issue_comment_triggers_delivery",
        "outbound": "test_github_token::test_post_and_update_comment",
        "isolation": "test_github_inbound::test_github_event_foreign_install_not_routed",
    },
}

_REQUIRED = {"inbound", "outbound", "isolation"}


def test_every_provider_has_inbound_outbound_isolation():
    discovered = set(discover_providers())
    assert discovered == set(PROVIDER_COVERAGE), (
        "provider coverage map out of sync with registry: "
        f"missing={discovered - set(PROVIDER_COVERAGE)} "
        f"orphan={set(PROVIDER_COVERAGE) - discovered}"
    )
    for name, cov in PROVIDER_COVERAGE.items():
        assert _REQUIRED <= set(cov), f"{name} missing {_REQUIRED - set(cov)}"


def test_discovered_providers_are_all_wired_in_create_app(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "x")
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    app = create_app(start_background=False)
    assert set(app.state.providers) == set(discover_providers()), (
        "a provider class exists but create_app does not wire it (or vice-versa)"
    )


def test_cited_tests_exist():
    """The cited inbound/outbound/isolation tests must be real callables."""
    import importlib as il
    for cov in PROVIDER_COVERAGE.values():
        for ref in cov.values():
            mod_name, _, test_name = ref.partition("::")
            mod = il.import_module(f"tests.{mod_name}")
            assert hasattr(mod, test_name), f"missing cited test {ref}"
