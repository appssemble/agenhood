from __future__ import annotations

import pytest

from control_plane.routers.auth import LoginRequest, build_login_response, build_me

pytestmark = pytest.mark.unit


def test_login_request_lowercases_email():
    req = LoginRequest(email="Owner@Example.COM", password="x")
    assert req.email == "owner@example.com"


def test_build_login_response_shape():
    user = {"id": "usr_1", "name": "Ada", "must_change_password": True}
    body = build_login_response(user, active_tenant_id="ten_1",
                                tenants=[{"id": "ten_1", "role": "admin"}])
    assert body == {
        "id": "usr_1", "role": "admin", "name": "Ada", "must_change_password": True,
        "active_tenant_id": "ten_1",
        "tenants": [{"id": "ten_1", "role": "admin"}],
        "needs_tenant_selection": False,
    }


def test_build_login_response_flags_selection_when_no_active_tenant():
    user = {"id": "usr_1", "name": "Ada", "must_change_password": False}
    body = build_login_response(user, active_tenant_id=None,
                                tenants=[{"id": "a", "role": "member"},
                                         {"id": "b", "role": "member"}])
    assert body["needs_tenant_selection"] is True


_USER = {
    "id": "usr_1", "role": "owner", "name": "Ada",
    "email": "ada@example.com", "must_change_password": False, "is_staff": False,
}


def test_build_me_includes_active_tenant_and_membership_list():
    from control_plane.tenant_defaults import merge_limits

    limits = {"allowed_models": ["claude-sonnet-4-6"], "allowed_drivers": ["vanilla"]}
    tenant = {"id": "ten_1", "name": "Acme", "limits": limits, "status": "active"}
    me = build_me(
        _USER, tenant,
        active_tenant_id="ten_1",
        tenants=[{"id": "ten_1", "name": "Acme", "role": "owner"}],
    )
    assert me["principal"] == "user"
    assert me["email"] == "ada@example.com"
    assert me["active_tenant_id"] == "ten_1"
    # /me reports *effective* limits: current defaults with the tenant's explicit
    # overrides layered on top (here an explicit allowed_drivers restriction).
    assert me["tenant"] == {
        "id": "ten_1", "name": "Acme", "limits": merge_limits(limits),
    }
    assert me["tenant"]["limits"]["allowed_drivers"] == ["vanilla"]
    assert me["tenant"]["limits"]["allowed_models"] == ["claude-sonnet-4-6"]
    assert me["tenants"] == [{"id": "ten_1", "name": "Acme", "role": "owner"}]


def test_build_me_tolerates_no_active_tenant():
    me = build_me(_USER, None, active_tenant_id=None, tenants=[])
    assert me["tenant"] is None
    assert me["active_tenant_id"] is None
    assert me["tenants"] == []
    assert me["email"] == "ada@example.com"
