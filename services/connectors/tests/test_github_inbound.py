from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.pool
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from connectors.app import create_app
from connectors.connections_service import build_connection_row
from connectors.ids import new_id
from connectors.orchestrator import handle_event
from connectors.providers.github import GitHubProvider
from connectors.tables import (
    connections,
    container_bindings,
    deliveries,
    metadata,
    routing_rules,
)

pytestmark = pytest.mark.unit
KEY = os.urandom(32)
SECRET = "gh-webhook-secret"
INSTALL = "987"


def _strip(row: dict) -> dict:  # type: ignore[type-arg]
    return {k: v for k, v in row.items() if not k.startswith("_")}


class _GithubInbound(GitHubProvider):
    """Real verify_webhook + normalize_event; outbound HTTP stubbed."""

    def __init__(self) -> None:
        super().__init__(app_id="1", private_key_pem="", webhook_secret=SECRET)

    async def mint_token(self, connection_row, master_key):  # type: ignore[override]
        return "tok"

    async def post_initial(self, token, origin_ref, body):  # type: ignore[override]
        return {"repo": origin_ref["repo"], "comment_id": 1}

    async def update_message(self, token, handle, body):  # type: ignore[override]
        return None


class _FakeCP:
    async def submit_task(self, *, container_id, api_key, prompt, metadata):  # type: ignore[type-arg]
        return "tsk_gh"

    async def stream_events(self, *, container_id, task_id, api_key, after_seq=0):  # type: ignore[return]
        yield {"seq": 1, "type": "status_change",
               "payload": {"to": "succeeded", "result": {"output": "GH-OK"}, "error": None}}


def _issue_comment_payload() -> dict:  # type: ignore[type-arg]
    return {
        "action": "created",
        "repository": {"full_name": "org/api"},
        "issue": {"number": 42},
        "comment": {"id": 7, "body": "/agent run tests"},
        "installation": {"id": int(INSTALL)},
        "sender": {"login": "octocat"},
    }


@pytest.fixture
def gh_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(KEY).decode())
    db_url = f"sqlite+aiosqlite:///{tmp_path}/gh.db"
    now = datetime.now(UTC)
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="github", external_id=INSTALL,
        display_name="GitHub", access_token=None, refresh_token=None,
        token_expires_at=None, cp_api_key="tk_live_gh", scopes="",
        metadata={}, master_key=KEY,
    )

    async def _setup() -> None:
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.run_sync(metadata.create_all)
        async with eng.begin() as txn:
            await txn.execute(sa.insert(connections).values(**_strip(conn_row)))
            await txn.execute(sa.insert(container_bindings).values(
                id=new_id("bnd"), connection_id=conn_row["id"], container_id="cnt_1",
                tenant_id="ten_1", enabled=True, resource_filters={},
                created_at=now, updated_at=now))
            await txn.execute(sa.insert(routing_rules).values(
                id=new_id("rul"), connection_id=conn_row["id"], tenant_id="ten_1",
                priority=10, match={"repo": "org/api"}, target={"container_id": "cnt_1"},
                input_template="{{ text }}", surface=["result"], enabled=True,
                created_at=now, updated_at=now))
        await eng.dispose()

    import asyncio
    asyncio.run(_setup())

    app = create_app(start_background=False)
    eng = create_async_engine(db_url)
    app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
    app.state.master_key = KEY
    app.state.providers = {"github": _GithubInbound()}
    app.state.cp_client = _FakeCP()
    return TestClient(app), db_url


def test_github_issue_comment_triggers_delivery(gh_client):
    tc, db_url = gh_client
    raw = json.dumps(_issue_comment_payload()).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = tc.post("/v1/webhooks/github", content=raw, headers={
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": "d-1",
        "Content-Type": "application/json",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "triggered"

    async def _deliveries():
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            rows = (await conn.execute(sa.select(deliveries))).mappings().all()
        await eng.dispose()
        return [dict(x) for x in rows]

    import asyncio
    rows = asyncio.run(_deliveries())
    assert len(rows) == 1 and rows[0]["task_id"] == "tsk_gh"


@pytest.mark.asyncio
async def test_github_event_foreign_install_not_routed():
    eng = create_async_engine(
        "sqlite+aiosqlite://", poolclass=sqlalchemy.pool.StaticPool,
        connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    now = datetime.now(UTC)
    conn_row = build_connection_row(
        tenant_id="ten_1", provider="github", external_id=INSTALL,
        display_name="GitHub", access_token=None, refresh_token=None,
        token_expires_at=None, cp_api_key="tk_live_gh", scopes="",
        metadata={}, master_key=KEY)
    async with factory() as s:
        await s.execute(sa.insert(connections).values(**_strip(conn_row)))
        await s.execute(sa.insert(container_bindings).values(
            id=new_id("bnd"), connection_id=conn_row["id"], container_id="cnt_1",
            tenant_id="ten_1", enabled=True, resource_filters={},
            created_at=now, updated_at=now))
        await s.execute(sa.insert(routing_rules).values(
            id=new_id("rul"), connection_id=conn_row["id"], tenant_id="ten_1",
            priority=10, match={}, target={"container_id": "cnt_1"},
            input_template="{{ text }}", surface=["result"], enabled=True,
            created_at=now, updated_at=now))
        await s.commit()

    provider = _GithubInbound()
    payload = _issue_comment_payload()
    payload["installation"]["id"] = 654  # foreign installation
    payload["_github_event"] = "issue_comment"
    payload["_delivery_id"] = "d-foreign"

    result = await handle_event(
        provider=provider, payload=payload, factory=factory,
        cp_client=_FakeCP(), master_key=KEY, coalesce_ms=0,
        background_tasks=BackgroundTasks())
    assert result == {"status": "no_route"}
    async with factory() as s:
        rows = (await s.execute(sa.select(deliveries))).mappings().all()
    assert len(rows) == 0
