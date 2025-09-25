from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from control_plane.auth.passwords import hash_password
from control_plane.auth.principal import Principal, resolve_from_inputs
from control_plane.auth.tokens import API_KEY_PREFIX_LEN, generate_api_key, hash_token


def now() -> datetime:
    return datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


class FakeRepo:
    def __init__(self) -> None:
        self.api_keys: dict = {}      # prefix -> {tenant_id, key_hash, status, id}
        self.sessions: dict = {}      # token_hash -> session row
        self.users: dict = {}         # id -> user row
        self.memberships: dict = {}   # user_id -> list of {tenant_id, role}

    async def get_active_api_keys_by_prefix(self, prefix: str) -> list[dict]:
        k = self.api_keys.get(prefix)
        if k and k["status"] == "active":
            return [k]
        return []

    async def get_session_by_token_hash(self, th: str) -> dict | None:
        return self.sessions.get(th)

    async def get_user(self, uid: str) -> dict | None:
        return self.users.get(uid)

    async def touch_api_key(self, key_id: str) -> None:  # best-effort last_used_at
        pass

    async def get_active_memberships(self, user_id: str) -> list[dict]:
        return self.memberships.get(user_id, [])

    async def persist_session_slide(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        pass


@pytest.mark.asyncio
async def test_api_key_resolves_to_member() -> None:
    repo = FakeRepo()
    secret, prefix = generate_api_key()
    repo.api_keys[prefix] = {"id": "key_1", "tenant_id": "ten_1",
                             "key_hash": hash_password(secret), "status": "active"}
    p = await resolve_from_inputs(repo, authorization=f"Bearer {secret}",
                                  cookie_token=None, admin_api_key_env=None, at=now())
    assert p == Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)


@pytest.mark.asyncio
async def test_api_key_wrong_secret_same_prefix_is_unauthorized() -> None:
    repo = FakeRepo()
    secret, prefix = generate_api_key()
    repo.api_keys[prefix] = {"id": "key_1", "tenant_id": "ten_1",
                             "key_hash": hash_password(secret), "status": "active"}
    forged = secret[:API_KEY_PREFIX_LEN] + "tampered_suffix_xxxxxxxxxxxxxxxxxxxxx"
    p = await resolve_from_inputs(repo, authorization=f"Bearer {forged}",
                                  cookie_token=None, admin_api_key_env=None, at=now())
    assert p is None


@pytest.mark.asyncio
async def test_session_cookie_resolves_to_user_role() -> None:
    repo = FakeRepo()
    token = "session-token-abc"
    repo.sessions[hash_token(token)] = {
        "id": "ses_1", "user_id": "usr_1", "active_tenant_id": "ten_1",
        "expires_at": now() + timedelta(days=5), "revoked_at": None,
        "last_seen_at": now(), "created_at": now(),
    }
    repo.users["usr_1"] = {"id": "usr_1", "is_staff": False, "status": "active"}
    repo.memberships["usr_1"] = [{"tenant_id": "ten_1", "role": "admin"}]
    p = await resolve_from_inputs(repo, authorization=None, cookie_token=token,
                                  admin_api_key_env=None, at=now())
    assert p == Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_1",
                         available_tenant_ids=("ten_1",))


@pytest.mark.asyncio
async def test_staff_session_resolves_to_staff() -> None:
    repo = FakeRepo()
    token = "staff-token"
    repo.sessions[hash_token(token)] = {
        "id": "ses_2", "user_id": "usr_staff",
        "expires_at": now() + timedelta(days=5), "revoked_at": None,
        "last_seen_at": now(), "created_at": now(),
    }
    repo.users["usr_staff"] = {"id": "usr_staff", "tenant_id": None, "role": "member",
                               "is_staff": True, "status": "active"}
    p = await resolve_from_inputs(repo, authorization=None, cookie_token=token,
                                  admin_api_key_env=None, at=now())
    assert p is not None
    assert p.is_staff is True and p.tenant_id is None


@pytest.mark.asyncio
async def test_expired_session_is_unauthorized() -> None:
    repo = FakeRepo()
    token = "old"
    repo.sessions[hash_token(token)] = {
        "id": "ses_3", "user_id": "usr_1",
        "expires_at": now() - timedelta(days=1), "revoked_at": None,
        "last_seen_at": now(), "created_at": now(),
    }
    repo.users["usr_1"] = {"id": "usr_1", "tenant_id": "ten_1", "role": "member",
                           "is_staff": False, "status": "active"}
    assert await resolve_from_inputs(repo, authorization=None, cookie_token=token,
                                     admin_api_key_env=None, at=now()) is None


@pytest.mark.asyncio
async def test_disabled_user_is_unauthorized() -> None:
    repo = FakeRepo()
    token = "tok"
    repo.sessions[hash_token(token)] = {
        "id": "ses_4", "user_id": "usr_1",
        "expires_at": now() + timedelta(days=5), "revoked_at": None,
        "last_seen_at": now(), "created_at": now(),
    }
    repo.users["usr_1"] = {"id": "usr_1", "tenant_id": "ten_1", "role": "member",
                           "is_staff": False, "status": "disabled"}
    assert await resolve_from_inputs(repo, authorization=None, cookie_token=token,
                                     admin_api_key_env=None, at=now()) is None


@pytest.mark.asyncio
async def test_bootstrap_admin_key_resolves_to_staff() -> None:
    repo = FakeRepo()
    p = await resolve_from_inputs(repo, authorization="Bearer boot-secret",
                                  cookie_token=None, admin_api_key_env="boot-secret", at=now())
    assert p is not None
    assert p.is_staff is True and p.tenant_id is None and p.user_id is None


@pytest.mark.asyncio
async def test_no_credentials_is_unauthorized() -> None:
    repo = FakeRepo()
    assert await resolve_from_inputs(repo, authorization=None, cookie_token=None,
                                     admin_api_key_env=None, at=now()) is None
