"""Route-inventory gate for the connectors service.

Every (METHOD, path) pair registered in the connectors FastAPI app must appear
in TESTED_PATHS or in ALLOW. A new endpoint without a contract test causes this
gate to fail, naming the uncovered route(s).

Framework routes (/docs, /openapi.json, /redoc, /docs/oauth2-redirect) are
already excluded by collect_routes() via _framework_defaults, so they do NOT
appear in ALLOW (putting them there would trigger the stale-entry check).
"""
from __future__ import annotations

import pytest

from agentcore.testing.route_inventory import assert_routes_covered
from connectors.app import create_app

pytestmark = pytest.mark.unit

# Every (METHOD, path) pair that has >=1 contract test.
# A new endpoint not listed here will fail this gate until a test is added.
TESTED_PATHS = {
    # health
    ("GET", "/healthz"),
    # connections
    ("GET", "/v1/connections"),
    ("DELETE", "/v1/connections/{connection_id}"),
    # bindings
    ("GET", "/v1/bindings"),
    ("PUT", "/v1/bindings"),
    # routing rules
    ("GET", "/v1/routing-rules"),
    ("PUT", "/v1/routing-rules"),
    ("DELETE", "/v1/routing-rules/{rule_id}"),
    # oauth callbacks
    ("GET", "/v1/oauth/slack/callback"),
    ("GET", "/v1/oauth/github/callback"),
    # webhooks
    ("POST", "/v1/webhooks/{provider_name}"),
}

# Framework routes are already excluded by collect_routes(); no entries needed.
ALLOW: tuple[()] = ()


def test_every_connectors_route_has_a_contract_test():
    """Fails if any registered connectors route lacks a contract test."""
    app = create_app(start_background=False)
    assert_routes_covered(app, TESTED_PATHS, allow=ALLOW)
