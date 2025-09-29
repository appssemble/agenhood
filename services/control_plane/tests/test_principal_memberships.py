from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from control_plane.auth.principal import Principal, resolve_from_inputs
from control_plane.auth.tokens import hash_token

pytestmark = pytest.mark.unit


def test_principal_has_available_tenant_ids_default_empty():
    p = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_1")
    assert p.available_tenant_ids == ()


def test_principal_carries_available_tenant_ids():
    p = Principal(
        tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_1",
        available_tenant_ids=("ten_1", "ten_2"),
    )
    assert p.available_tenant_ids == ("ten_1", "ten_2")


class FakeRepo:
    """In-memory PrincipalRepo for unit-testing resolve_from_inputs."""

    def __init__(self, *, user, session, memberships, existing_tenants=()):
        self._user = user
        self._session = session
        self._memberships = memberships
        self._existing_tenants = set(existing_tenants)

    async def get_active_api_keys_by_prefix(self, prefix):  # pragma: no cover - unused here
        return []

    async def get_session_by_token_hash(self, token_hash):
        return self._session

    async def get_user(self, user_id):
        return self._user

    async def get_active_memberships(self, user_id):
        return self._memberships

    async def touch_api_key(self, key_id):  # pragma: no cover - unused here
        return None

    async def persist_session_slide(self, session_id, last_seen_at, expires_at):
        return None

    async def tenant_exists(self, tenant_id):
        return tenant_id in self._existing_tenants


def _session_row(active_tenant_id):
    now = datetime.now(UTC)
    return {
        "id": "ses_1",
        "user_id": "usr_1",
        "token_hash": hash_token("cookie-token"),
        "active_tenant_id": active_tenant_id,
        "created_at": now,
        "last_seen_at": now,
        "expires_at": now + timedelta(days=1),
        "revoked_at": None,
    }


_ACTIVE_USER = {"id": "usr_1", "is_staff": False, "status": "active", "tenant_id": None, "role": "member"}


@pytest.mark.asyncio
async def test_resolve_single_membership_uses_active_tenant():
    repo = FakeRepo(
        user=_ACTIVE_USER,
        session=_session_row("ten_a"),
        memberships=[{"tenant_id": "ten_a", "role": "owner"}],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.tenant_id == "ten_a"
    assert p.role == "owner"
    assert p.is_staff is False
    assert p.available_tenant_ids == ("ten_a",)


@pytest.mark.asyncio
async def test_resolve_multi_membership_picks_selected_role():
    repo = FakeRepo(
        user=_ACTIVE_USER,
        session=_session_row("ten_b"),
        memberships=[
            {"tenant_id": "ten_a", "role": "owner"},
            {"tenant_id": "ten_b", "role": "member"},
        ],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.tenant_id == "ten_b"
    assert p.role == "member"
    assert set(p.available_tenant_ids) == {"ten_a", "ten_b"}


@pytest.mark.asyncio
async def test_resolve_no_active_tenant_is_limbo():
    repo = FakeRepo(
        user=_ACTIVE_USER,
        session=_session_row(None),
        memberships=[
            {"tenant_id": "ten_a", "role": "owner"},
            {"tenant_id": "ten_b", "role": "member"},
        ],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.tenant_id is None
    assert p.role == "member"
    assert p.is_staff is False
    assert set(p.available_tenant_ids) == {"ten_a", "ten_b"}


@pytest.mark.asyncio
async def test_resolve_stale_active_tenant_falls_back_to_limbo():
    repo = FakeRepo(
        user=_ACTIVE_USER,
        session=_session_row("ten_gone"),
        memberships=[{"tenant_id": "ten_a", "role": "member"}],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.tenant_id is None
    assert p.available_tenant_ids == ("ten_a",)


@pytest.mark.asyncio
async def test_resolve_staff_unchanged():
    repo = FakeRepo(
        user={"id": "usr_s", "is_staff": True, "status": "active"},
        session=_session_row(None),
        memberships=[],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.is_staff is True
    assert p.tenant_id is None
    assert p.available_tenant_ids == ()


@pytest.mark.asyncio
async def test_resolve_zero_memberships_is_limbo():
    repo = FakeRepo(
        user=_ACTIVE_USER,
        session=_session_row(None),
        memberships=[],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.tenant_id is None
    assert p.role == "member"
    assert p.is_staff is False
    assert p.available_tenant_ids == ()


@pytest.mark.asyncio
async def test_resolve_staff_impersonates_existing_tenant():
    repo = FakeRepo(
        user={"id": "usr_s", "is_staff": True, "status": "active"},
        session=_session_row("ten_x"),
        memberships=[],
        existing_tenants=["ten_x"],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.is_staff is True
    assert p.tenant_id == "ten_x"
    assert p.role == "owner"


@pytest.mark.asyncio
async def test_resolve_staff_with_no_active_tenant_is_cross_tenant():
    repo = FakeRepo(
        user={"id": "usr_s", "is_staff": True, "status": "active"},
        session=_session_row(None),
        memberships=[],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.is_staff is True
    assert p.tenant_id is None


@pytest.mark.asyncio
async def test_resolve_staff_stale_tenant_falls_back_to_cross_tenant():
    repo = FakeRepo(
        user={"id": "usr_s", "is_staff": True, "status": "active"},
        session=_session_row("ten_gone"),
        memberships=[],
        existing_tenants=[],
    )
    p = await resolve_from_inputs(
        repo, authorization=None, cookie_token="cookie-token", admin_api_key_env=None)
    assert p.is_staff is True
    assert p.tenant_id is None
