"""E2E: vanilla loop with an attached skill and an attached MCP server."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}


# POST /v1/mcp-servers rejects non-https URLs in production (test_mcp_service.py
# ::test_validate_rejects_non_https). The stub server runs plain HTTP on the
# internal Docker test network (no TLS termination available there), so this
# opts in via the same env-var pattern skills_fetch.py uses for
# AGENHOOD_ALLOW_FILE_SKILL_SOURCE.
@pytest.fixture(autouse=True)
def _allow_http_mcp_source(monkeypatch):
    monkeypatch.setenv("AGENHOOD_ALLOW_HTTP_MCP_SOURCE", "1")


async def _seed_admin_session(app, tenant_id: str) -> str:
    """Insert an owner user + membership + session for *tenant_id* and return
    the raw session token.

    POST /v1/skills and /v1/mcp-servers are admin-gated (require_admin), and
    tenant API keys always resolve to role='member' (see
    control_plane.auth.principal.resolve_from_inputs) -- API-key auth can never
    satisfy that gate. The seed tenant has no owner user by default, so tests
    that create a skill/MCP server need one; this mirrors what
    POST /admin/v1/tenants + POST /v1/auth/login would produce, without
    requiring the bootstrap admin key or a second tenant (which would need its
    own seeded LLM credential).
    """
    from sqlalchemy import select

    from control_plane.auth.passwords import hash_password
    from control_plane.auth.sessions import build_session_row
    from control_plane.ids_compat import new_id
    from control_plane.tables import memberships, sessions, users

    now = datetime.now(UTC)
    async with app.state.session_factory() as s:
        # idx_membership_one_owner allows only one active owner per tenant;
        # the Postgres container (and its seed data) is session-scoped, so a
        # second test in the same run must reuse the owner created by the
        # first rather than re-inserting one.
        existing = (await s.execute(
            select(memberships.c.user_id).where(
                memberships.c.tenant_id == tenant_id,
                memberships.c.role == "owner",
                memberships.c.status == "active",
            )
        )).scalar_one_or_none()
        if existing is not None:
            user_id = existing
        else:
            user_id = new_id("usr")
            await s.execute(users.insert().values(
                id=user_id, email=f"{user_id}@test.invalid", name="Test Admin",
                password_hash=hash_password("unused"), is_staff=False,
                must_change_password=False, status="active",
                created_at=now, updated_at=now,
            ))
            await s.execute(memberships.insert().values(
                id=new_id("mem"), user_id=user_id, tenant_id=tenant_id,
                role="owner", status="active", created_at=now, updated_at=now,
            ))
        token, session_row = build_session_row(user_id=user_id, at=now)
        await s.execute(sessions.insert().values(
            **session_row, active_tenant_id=tenant_id,
        ))
        await s.commit()
    return token


async def _run_scripted(client, cid: str, script: dict) -> tuple[str, list[dict]]:
    ts = await client.post(
        f"/v1/containers/{cid}/tasks", headers=_HEADERS,
        json={"prompt": "@@SCRIPT@@ " + json.dumps(script)},
    )
    assert ts.status_code == 200, ts.text
    tid = ts.json()["task_id"]
    terminal, tool_results = None, []
    sse_headers = {**_HEADERS, "Accept": "text/event-stream"}
    async with client.stream(
        "GET", f"/v1/containers/{cid}/tasks/{tid}/events",
        headers=sse_headers, timeout=120,
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[len("data:"):].strip())
            if ev["type"] == "tool_result":
                tool_results.append(ev["payload"])
            if ev["type"] == "status_change" and ev["payload"].get("to") in (
                "completed", "failed", "timed_out", "cancelled",
            ):
                terminal = ev["payload"]["to"]
                break
    return terminal, tool_results


async def test_skill_loads_end_to_end(seeded_app):
    transport = ASGITransport(app=seeded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _seed_admin_session(seeded_app, "ten_seed")
        client.cookies.set("agent_session", admin_token)
        # Session cookie only -- an Authorization: Bearer tk_live_... header
        # would short-circuit auth resolution to the (member-role) API-key path.
        r = await client.post("/v1/skills", json={
            "name": "greeting-format",
            "description": "How to format greetings",
            "body": "Always greet with: SKILL-BODY-MARKER",
        })
        assert r.status_code in (200, 201), r.text
        skill_id = r.json()["id"]
        r = await client.post("/v1/containers", headers=_HEADERS, json={
            "name": "skills-e2e",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7",
                       "tools": ["read_file", "bash"], "skills": [skill_id]},
        })
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            terminal, results = await _run_scripted(client, cid, {"turns": [
                {"tool": "skill", "input": {"name": "greeting-format"}},
                # Bundled skill files must be reachable from SANDBOXED
                # subprocesses (uid-dropped bash/python), not just the shim's
                # in-process file tools — regression test for the root-700
                # .agent-runtime traversal bug.
                {"tool": "bash", "input": {"command":
                    "cat /workspace/.agent-runtime/skills/greeting-format/SKILL.md"}},
                {"done": {"success": True, "output": "used skill"}},
            ]})
            assert terminal == "completed"
            assert results and results[0]["ok"]
            assert "SKILL-BODY-MARKER" in results[0]["content"]
            assert "Base directory for this skill:" in results[0]["content"]
            assert results[1]["ok"], (
                f"sandboxed bash could not read skill file: {results[1]['content']}"
            )
            assert "SKILL-BODY-MARKER" in results[1]["content"]
        finally:
            await client.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)


async def test_mcp_tool_end_to_end(seeded_app, stub_mcp):
    transport = ASGITransport(app=seeded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _seed_admin_session(seeded_app, "ten_seed")
        client.cookies.set("agent_session", admin_token)
        r = await client.post("/v1/mcp-servers", json={
            "name": "stub", "description": "test echo server", "url": stub_mcp,
        })
        assert r.status_code in (200, 201), r.text
        mcp_id = r.json()["id"]
        r = await client.post("/v1/containers", headers=_HEADERS, json={
            "name": "mcp-e2e",
            "config": {"driver": "vanilla", "model": "claude-opus-4-7",
                       "tools": [], "mcp_servers": [mcp_id]},
        })
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            terminal, results = await _run_scripted(client, cid, {"turns": [
                {"tool": "mcp__stub__echo", "input": {"text": "roundtrip"}},
                {"done": {"success": True, "output": "used mcp"}},
            ]})
            assert terminal == "completed"
            assert results and results[0]["ok"]
            assert "mcp-echo:roundtrip" in results[0]["content"]
        finally:
            await client.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
