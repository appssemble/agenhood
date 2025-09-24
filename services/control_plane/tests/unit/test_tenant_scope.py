"""_tenant_scope: staff scope resolution, including impersonation.

When a staff user impersonates a workspace, the active tenant is on the
principal; inviting a user there must not require an explicit body tenant_id.
"""
import pytest

from control_plane.auth.principal import Principal
from control_plane.errors import APIError
from control_plane.routers.users import _tenant_scope

pytestmark = pytest.mark.unit


def _staff(tenant_id: str | None) -> Principal:
    return Principal(
        tenant_id=tenant_id,
        role="owner" if tenant_id else "member",
        is_staff=True,
        user_id="usr_admin",
    )


def test_staff_uses_impersonated_active_tenant() -> None:
    # Impersonating a workspace -> scope to that active tenant, no body needed.
    assert _tenant_scope(_staff("ten_imp")) == "ten_imp"


def test_staff_body_tenant_overrides_active() -> None:
    assert _tenant_scope(_staff("ten_imp"), "ten_explicit") == "ten_explicit"


def test_staff_with_no_tenant_at_all_errors() -> None:
    with pytest.raises(APIError) as ei:
        _tenant_scope(_staff(None))
    assert ei.value.status_code == 400


def test_tenant_admin_scoped_to_own_tenant() -> None:
    p = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")
    assert _tenant_scope(p, "ten_other") == "ten_1"
