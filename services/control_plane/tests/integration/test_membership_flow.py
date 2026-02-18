"""End-to-end multi-tenant membership flow over HTTP (ASGITransport).

Mirrors tests/integration/test_auth_flow.py: bootstrap tenants via the admin
key, then exercise login / select-tenant / users-as-membership.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_ADMIN_AUTH = {"Authorization": "Bearer boot-test-key"}


async def _bootstrap_tenant(client: AsyncClient, *, suffix: str) -> dict:
    r = await client.post(
        "/admin/v1/tenants",
        headers=_ADMIN_AUTH,
        json={
            "name": f"Acme-{suffix}",
            "limits": {},
            "owner": {
                "email": f"owner-{suffix}@acme.example.com",
                "name": "Owner",
                "password": "pw-initial",
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_login_returns_membership_shape(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="loginshape")
        r = await client.post(
            "/v1/auth/login",
            json={"email": "owner-loginshape@acme.example.com", "password": "pw-initial"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Shape assertions only: owner membership is created in a later task (Task 9),
        # so do NOT assert tenants is non-empty here.
        assert set(body.keys()) >= {
            "id", "role", "name", "must_change_password",
            "active_tenant_id", "tenants", "needs_tenant_selection",
        }
        assert isinstance(body["tenants"], list)
        assert isinstance(body["needs_tenant_selection"], bool)


async def test_select_tenant_rejects_non_member(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="nonmember")
        other = await _bootstrap_tenant(client, suffix="forbidden")
        await client.post(
            "/v1/auth/login",
            json={"email": "owner-nonmember@acme.example.com", "password": "pw-initial"},
        )
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": other["id"]})
        assert r.status_code == 403, r.text


async def test_create_tenant_creates_owner_membership(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="ownmbr")
        r = await client.post(
            "/v1/auth/login",
            json={"email": "owner-ownmbr@acme.example.com", "password": "pw-initial"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenants"][0]["role"] == "owner"
        assert body["active_tenant_id"] == body["tenants"][0]["id"]


async def test_admin_user_list_shows_tenant_role_from_membership(
    app_with_admin_key: object,
) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        t1 = await _bootstrap_tenant(client, suffix="adminlist")
        r = await client.get(
            f"/admin/v1/users?tenant_id={t1['id']}", headers=_ADMIN_AUTH)
        assert r.status_code == 200, r.text
        users = r.json()["users"]
        owner = next(u for u in users if u["email"] == "owner-adminlist@acme.example.com")
        assert owner["role"] == "owner"          # sourced from membership
        assert owner["tenant_id"] == t1["id"]


async def _login(client: AsyncClient, email: str, pw: str = "pw-initial") -> dict:  # type: ignore[type-arg]
    r = await client.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_user_new_identity(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="newid")
        await _login(client, "owner-newid@acme.example.com")
        r = await client.post(
            "/v1/users",
            json={"email": "alice@x.io", "name": "Alice", "role": "member",
                  "password": "pw-alice"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["must_change_password"] is True


async def test_create_user_existing_identity_silently_adds_membership(
    app_with_admin_key: object,
) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="addA")
        await _bootstrap_tenant(client, suffix="addB")
        await _login(client, "owner-addA@acme.example.com")
        r = await client.post(
            "/v1/users",
            json={"email": "owner-addB@acme.example.com", "name": "ignored",
                  "role": "member"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["must_change_password"] is False


async def test_create_user_duplicate_membership_409(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="dup")
        await _login(client, "owner-dup@acme.example.com")
        await client.post("/v1/users",
                          json={"email": "bob@x.io", "name": "Bob", "role": "member",
                                "password": "pw-bob"})
        r = await client.post("/v1/users",
                              json={"email": "bob@x.io", "name": "Bob", "role": "member"})
        assert r.status_code == 409, r.text
        assert "member of this workspace" in r.json()["error"]["message"].lower()


async def test_select_tenant_switches_active_and_role(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        t1 = await _bootstrap_tenant(client, suffix="multi1")
        t2 = await _bootstrap_tenant(client, suffix="multi2")
        # Staff adds owner-multi1 (an existing identity) as a member of tenant 2.
        r = await client.post(
            "/v1/users",
            headers=_ADMIN_AUTH,
            json={
                "email": "owner-multi1@acme.example.com",
                "name": "ignored",
                "role": "member",
                "tenant_id": t2["id"],
            },
        )
        assert r.status_code == 201, r.text

        # Login: 2 memberships → auto-selects owned tenant (t1); needs_tenant_selection is False.
        r = await client.post(
            "/v1/auth/login",
            json={"email": "owner-multi1@acme.example.com", "password": "pw-initial"},
        )
        body = r.json()
        assert body["needs_tenant_selection"] is False
        assert {m["id"] for m in body["tenants"]} == {t1["id"], t2["id"]}

        # Select tenant 1 → owner.
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": t1["id"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"active_tenant_id": t1["id"], "role": "owner"}

        # /me reflects it.
        me = await client.get("/v1/auth/me")
        assert me.json()["active_tenant_id"] == t1["id"]
        assert me.json()["role"] == "owner"

        # Switch to tenant 2 → member.
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": t2["id"]})
        assert r.json() == {"active_tenant_id": t2["id"], "role": "member"}


async def test_list_users_scopes_to_active_tenant(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="listA")
        await _login(client, "owner-listA@acme.example.com")
        await client.post("/v1/users",
                          json={"email": "carol@x.io", "name": "Carol", "role": "member",
                                "password": "pw-carol"})
        r = await client.get("/v1/users")
        assert r.status_code == 200, r.text
        emails = {u["email"] for u in r.json()["users"]}
        assert {"owner-lista@acme.example.com", "carol@x.io"} <= emails
        assert all("role" in u for u in r.json()["users"])


async def test_patch_user_changes_membership_role(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="role")
        await _login(client, "owner-role@acme.example.com")
        r = await client.post("/v1/users",
                              json={"email": "dan@x.io", "name": "Dan", "role": "member",
                                    "password": "pw-dan"})
        uid = r.json()["id"]
        r = await client.patch(f"/v1/users/{uid}", json={"role": "admin"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"
        r = await client.get("/v1/users")
        dan = next(u for u in r.json()["users"] if u["email"] == "dan@x.io")
        assert dan["role"] == "admin"


async def test_patch_user_cannot_demote_sole_owner(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="soleowner")
        me = await _login(client, "owner-soleowner@acme.example.com")
        owner_uid = me["id"]
        r = await client.patch(f"/v1/users/{owner_uid}", json={"role": "member"})
        assert r.status_code == 409, r.text


async def test_patch_user_name_updates_and_returns_it(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="rename")
        await _login(client, "owner-rename@acme.example.com")
        r = await client.post("/v1/users",
                              json={"email": "erin@x.io", "name": "Erin", "role": "member",
                                    "password": "pw-erin"})
        uid = r.json()["id"]
        r = await client.patch(f"/v1/users/{uid}", json={"name": "Erin Renamed"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Erin Renamed"
        # combined name + role change returns both
        r = await client.patch(f"/v1/users/{uid}", json={"name": "Erin Two", "role": "admin"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Erin Two"
        assert r.json()["role"] == "admin"


async def test_delete_user_removes_membership_only(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="delA")
        t2 = await _bootstrap_tenant(client, suffix="delB")
        await _login(client, "owner-delA@acme.example.com")
        # add owner-delB (existing identity) to tenant A as member
        await client.post("/v1/users",
                          json={"email": "owner-delB@acme.example.com", "name": "x",
                                "role": "member"})
        uid = next(u["id"] for u in (await client.get("/v1/users")).json()["users"]
                   if u["email"] == "owner-delb@acme.example.com")
        r = await client.delete(f"/v1/users/{uid}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "disabled"
        # removed from tenant A's list
        emails = {u["email"] for u in (await client.get("/v1/users")).json()["users"]}
        assert "owner-delb@acme.example.com" not in emails
        # identity still logs in (still owner of tenant B)
        login = await _login(client, "owner-delB@acme.example.com")
        assert login["tenants"][0]["id"] == t2["id"]


async def test_delete_user_cannot_remove_sole_owner(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="delowner")
        me = await _login(client, "owner-delowner@acme.example.com")
        r = await client.delete(f"/v1/users/{me['id']}")
        assert r.status_code == 409, r.text


async def test_login_auto_selects_owner_tenant_by_default(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        a = await _bootstrap_tenant(client, suffix="autoA")   # owner-autoA owns A
        b = await _bootstrap_tenant(client, suffix="autoB")
        # Add owner-autoA as a member of B (staff add-by-email).
        r = await client.post("/v1/users", headers=_ADMIN_AUTH, json={
            "email": "owner-autoA@acme.example.com", "name": "x", "role": "member",
            "tenant_id": b["id"]})
        assert r.status_code == 201, r.text
        # Login with no prior selected session -> default picks the OWNED tenant (A).
        body = await _login(client, "owner-autoA@acme.example.com")
        assert body["active_tenant_id"] == a["id"], body


async def test_login_resumes_most_recent_selected_tenant(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="recentA")
        b = await _bootstrap_tenant(client, suffix="recentB")
        await client.post("/v1/users", headers=_ADMIN_AUTH, json={
            "email": "owner-recentA@acme.example.com", "name": "x", "role": "member",
            "tenant_id": b["id"]})
        # First login (defaults to owned A), then explicitly switch to B.
        await _login(client, "owner-recentA@acme.example.com")
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": b["id"]})
        assert r.status_code == 200, r.text
        # New login should RESUME the most-recent selection (B), not the default (A).
        body2 = await _login(client, "owner-recentA@acme.example.com")
        assert body2["active_tenant_id"] == b["id"], body2


async def test_staff_impersonates_and_exits(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        acme = await _bootstrap_tenant(client, suffix="impA")
        r = await client.post("/admin/v1/staff", headers=_ADMIN_AUTH, json={
            "email": "ops@platform.example.com", "name": "Ops", "password": "pw-ops"})
        assert r.status_code == 201, r.text
        login = await _login(client, "ops@platform.example.com", pw="pw-ops")
        # Staff are always scoped to a workspace now (first tenant by default).
        assert login["active_tenant_id"] is not None

        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": acme["id"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"active_tenant_id": acme["id"], "role": "owner"}

        me = (await client.get("/v1/auth/me")).json()
        assert me["is_staff"] is True
        assert me["active_tenant_id"] == acme["id"]
        assert me["tenant"]["id"] == acme["id"]

        users = (await client.get("/v1/users")).json()["users"]
        assert any(u["email"] == "owner-impa@acme.example.com" for u in users)

        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": None})
        assert r.status_code == 200, r.text
        assert r.json() == {"active_tenant_id": None, "role": None}
        me2 = (await client.get("/v1/auth/me")).json()
        assert me2["active_tenant_id"] is None


async def test_staff_impersonate_missing_tenant_404(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await client.post("/admin/v1/staff", headers=_ADMIN_AUTH, json={
            "email": "ops2@platform.example.com", "name": "Ops2", "password": "pw-ops"})
        await _login(client, "ops2@platform.example.com", pw="pw-ops")
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": "ten_does_not_exist"})
        assert r.status_code == 404, r.text


async def test_member_cannot_clear_active_tenant(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="noclear")
        await _login(client, "owner-noclear@acme.example.com")
        r = await client.post("/v1/auth/select-tenant", json={"tenant_id": None})
        assert r.status_code == 400, r.text


async def test_staff_creates_workspace_and_owns_it(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        r = await client.post("/admin/v1/staff", headers=_ADMIN_AUTH, json={
            "email": "founder@platform.example.com", "name": "Founder", "password": "pw-found"})
        assert r.status_code == 201, r.text
        login = await _login(client, "founder@platform.example.com", pw="pw-found")
        staff_id = login["id"]

        r = await client.post("/admin/v1/tenants", json={"name": "Acme HQ"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["owner_id"] == staff_id
        tid = body["id"]

        users = (
            await client.get(f"/admin/v1/users?tenant_id={tid}", headers=_ADMIN_AUTH)
        ).json()["users"]
        owner = next(u for u in users if u["role"] == "owner")
        assert owner["email"] == "founder@platform.example.com"


async def test_staff_owns_multiple_workspaces(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await client.post("/admin/v1/staff", headers=_ADMIN_AUTH, json={
            "email": "multi@platform.example.com", "name": "Multi", "password": "pw-multi"})
        await _login(client, "multi@platform.example.com", pw="pw-multi")
        r1 = await client.post("/admin/v1/tenants", json={"name": "WS One"})
        r2 = await client.post("/admin/v1/tenants", json={"name": "WS Two"})
        assert r1.status_code == 201 and r2.status_code == 201, (r1.text, r2.text)
        assert r1.json()["id"] != r2.json()["id"]


async def test_create_tenant_owner_spec_path_still_works(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        r = await client.post(
            "/admin/v1/tenants",
            headers=_ADMIN_AUTH,
            json={
                "name": "Bootstrapped",
                "owner": {
                    "email": "owner-bootstrapped@acme.example.com",
                    "name": "Owner",
                    "password": "pw-x",
                },
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["owner_id"].startswith("usr_")


async def test_create_tenant_no_owner_no_user_session_400(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        r = await client.post("/admin/v1/tenants", headers=_ADMIN_AUTH, json={"name": "Ownerless"})
        assert r.status_code == 400, r.text


async def test_member_creates_workspace_and_owns_it(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="selfserve")
        me = await _login(client, "owner-selfserve@acme.example.com")
        r = await client.post("/v1/tenants", json={"name": "My Side Project"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["owner_id"] == me["id"]
        users = (
            await client.get(f"/admin/v1/users?tenant_id={body['id']}", headers=_ADMIN_AUTH)
        ).json()["users"]
        assert any(
            u["email"] == "owner-selfserve@acme.example.com" and u["role"] == "owner"
            for u in users
        )


async def test_api_key_cannot_create_workspace(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        r = await client.post("/v1/tenants", headers={"Authorization": "Bearer tk_live_seedkey"},
                              json={"name": "Nope"})
        assert r.status_code == 403, r.text


async def test_member_workspace_cap_enforced(app_member_cap2: object) -> None:
    transport = ASGITransport(app=app_member_cap2)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="capped")
        await _login(client, "owner-capped@acme.example.com")
        r = await client.post("/v1/tenants", json={"name": "Second"})
        assert r.status_code == 201, r.text
        r = await client.post("/v1/tenants", json={"name": "Third"})
        assert r.status_code == 403, r.text
        assert "limit" in r.json()["error"]["message"].lower()


async def test_staff_exempt_from_workspace_cap(app_member_cap2: object) -> None:
    transport = ASGITransport(app=app_member_cap2)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await client.post("/admin/v1/staff", headers=_ADMIN_AUTH, json={
            "email": "biz@platform.example.com", "name": "Biz", "password": "pw-biz"})
        await _login(client, "biz@platform.example.com", pw="pw-biz")
        for i in range(3):
            r = await client.post("/v1/tenants", json={"name": f"Staff WS {i}"})
            assert r.status_code == 201, (i, r.text)
