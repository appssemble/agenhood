"""RBAC gate-class matrix + route→gate-class meta-gate (Unit C, Task 3).

Two assertions:
1. test_every_mutating_route_has_a_known_gate_or_is_self_scoped
   Meta-gate: every POST/PATCH/DELETE/PUT route either resolves to a known
   gate class (require_admin / require_session_admin / require_staff) OR is
   listed in C.SELF_SCOPED_MUTATIONS.  Fails if a new route is added without
   a classification — preventing silent auth gaps.

2. test_role_gate_matrix
   Parametrized: for the require_admin gate class, each principal name is
   tested against a representative endpoint.  Asserts the *real* allow/deny
   status code so a change in the gate's actual behaviour trips the test.

Relationship to tests/test_role_matrix.py
   The existing test_role_matrix.py already locks require_session_admin and
   require_staff representative endpoints with hand-picked assertions.
   This module adds:
     (a) the require_admin gate class (no existing test covered it as a class)
     (b) the route→gate-class META-gate (uniform classification of every route)

Representative endpoint for require_admin
   The brief suggested POST /v1/mcp-servers, but that handler adds a secondary
   403 for staff with tenant_id=None ("MCP servers are tenant-scoped").
   Reality check: POST /v1/containers/{cid}/recover is used instead because:
     - It uses Depends(require_admin) as its gate
     - It exposes a local _session dependency that can be overridden
     - All allowed principals (admin/owner/staff) reach a not_found() 404
       via the null session (container not found), satisfying != 403
     - Denied principals (member/apikey) are rejected by require_admin → 403
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from control_plane.auth.principal import resolve_principal
from tests.api_contract import contracts as C
from tests.api_contract.gate_helpers import GATE_DEPS, gate_class, null_session_overrides

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Meta-gate
# ---------------------------------------------------------------------------


def test_every_mutating_route_has_a_known_gate_or_is_self_scoped() -> None:
    """Every POST/PATCH/DELETE/PUT route must either:

    - be role-gated by a known helper (require_admin /
      require_session_admin / require_staff), OR
    - be explicitly listed in C.SELF_SCOPED_MUTATIONS as reviewed.

    Adding a new mutating route without classifying it trips this test,
    preventing silent auth gaps from slipping into the route inventory.
    """
    app = C.make_app()
    unknown: list[tuple[list[str], str]] = []
    for full_path, r in C.iter_mutation_routes(app):
        methods = {m for m in (r.methods or []) if m in ("POST", "PATCH", "DELETE", "PUT")}
        if not methods:
            continue
        gc = gate_class(r)
        if gc is None and full_path not in C.SELF_SCOPED_MUTATIONS:
            unknown.append((sorted(methods), full_path))
    assert not unknown, (
        f"Mutating routes with no known gate + not in SELF_SCOPED_MUTATIONS: {unknown}\n"
        f"Known gates: {GATE_DEPS}\n"
        f"Self-scoped allow-list: {sorted(C.SELF_SCOPED_MUTATIONS)}"
    )


# ---------------------------------------------------------------------------
# Role × gate-class matrix
# ---------------------------------------------------------------------------

# Expected allow (True) / deny (False) for each gate class × principal.
# "allowed" means the gate itself passes; the downstream handler may still
# return a non-2xx status for business-logic reasons (e.g. 404 when the
# resource does not exist in the null session).
_EXPECT: dict[str, dict[str, bool]] = {
    # require_admin: staff OR role ∈ {admin, owner}
    # API-key principals (user_id=None) have role="member" → denied.
    "require_admin": {
        "member": False,
        "apikey": False,
        "admin":  True,
        "owner":  True,
        "staff":  True,
    },
    # require_session_admin and require_staff are already covered in
    # tests/test_role_matrix.py.  They are NOT duplicated here — only
    # require_admin is the net-new coverage that this module adds.
}

# Principals from contracts.py — same objects used by test_route_inventory.
_PRINCIPALS = {
    "member": C.P_MEMBER,   # role=member, is_staff=False, user_id set
    "apikey": C.P_APIKEY,   # role=member, is_staff=False, user_id=None
    "admin":  C.P_ADMIN,    # role=admin,  is_staff=False
    "owner":  C.P_OWNER,    # role=owner,  is_staff=False
    "staff":  C.P_STAFF,    # is_staff=True, tenant_id=None
}

# Representative endpoint per gate class actually exercised by this module.
# POST /v1/containers/{cid}/recover uses Depends(require_admin) as its gate
# and Depends(_session) (containers._session) which is overridden by
# null_session_overrides() — so a passing request returns 404 (container not
# found) rather than a real DB error.  No request body is needed.
_REP: dict[str, tuple[str, str, dict]] = {
    "require_admin": ("POST", "/v1/containers/c_x/recover", {}),
}


@pytest.mark.parametrize("role_name", list(_PRINCIPALS))
@pytest.mark.parametrize("gate", list(_REP))
def test_role_gate_matrix(gate: str, role_name: str) -> None:
    """Assert the real allow/deny status for gate × principal.

    For allowed principals: asserts status != 403.
    For denied principals:  asserts status == 403 with error.code == "forbidden".

    The null session override ensures that gate-passing requests don't crash
    on a real DB connection — they return 404 (resource not found) instead.
    """
    method, url, body = _REP[gate]
    app = C.make_app()
    app.dependency_overrides[resolve_principal] = lambda: _PRINCIPALS[role_name]
    app.dependency_overrides.update(null_session_overrides(app))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.request(method, url, json=body or None)
    finally:
        app.dependency_overrides.clear()

    allowed = _EXPECT[gate][role_name]
    if allowed:
        assert r.status_code != 403, (
            f"gate={gate!r} role={role_name!r}: expected gate to pass "
            f"(status != 403) but got {r.status_code}; body={r.text!r}"
        )
    else:
        assert r.status_code == 403, (
            f"gate={gate!r} role={role_name!r}: expected 403 Forbidden "
            f"but got {r.status_code}; body={r.text!r}"
        )
        assert r.json()["error"]["code"] == "forbidden", (
            f"gate={gate!r} role={role_name!r}: error.code != 'forbidden'; body={r.text!r}"
        )
