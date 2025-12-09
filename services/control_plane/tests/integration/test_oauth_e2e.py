from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import httpx
import pytest
import respx

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_KEY = b"A" * 32


def _jwt_account(acct: str) -> str:
    import base64
    import json

    def seg(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{seg({'alg':'none'})}.{seg({'chatgpt_account_id': acct})}.s"


@respx.mock
@pytest.mark.asyncio
async def test_poller_then_selection_uses_oauth(migrated_db: str) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.config import Settings
    from control_plane.db import make_engine, make_session_factory
    from control_plane.models_db import tenants
    from control_plane.oauth_events import OAuthEventBus
    from control_plane.oauth_service import create_connection, oauth_poll_sweep
    from control_plane.routers.tasks import pick_provider_credential

    s = Settings.from_env()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_code": "ac_1",
                "code_verifier": "cv_1",
                "status": "authorized",
            },
        )
    )
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc-LIVE",
                "refresh_token": "ref-LIVE",
                "id_token": _jwt_account("acct_777"),
                "expires_in": 3600,
            },
        )
    )

    class _S:
        database_url = migrated_db

    engine = make_engine(_S())  # type: ignore[arg-type]
    factory = make_session_factory(engine)
    try:
        async with factory() as sess:
            await sess.execute(
                sa.insert(tenants).values(
                    id="ten_e2e_oauth",
                    name="t",
                    limits={},
                    status="active",
                    created_at=datetime.now(UTC),
                )
            )
            await create_connection(
                sess,
                tenant_id="ten_e2e_oauth",
                provider="openai",
                device_code=json.dumps({"device_auth_id": "da_1", "user_code": "UC-1"}),
                expires_in=900,
                master_key=_KEY,
            )
            await sess.commit()

        async with factory() as db:
            await oauth_poll_sweep(
                db, None, None, settings=s, master_key=_KEY, event_bus=OAuthEventBus()
            )

        async with factory() as sess:
            rows = [
                dict(r)
                for r in (
                    await sess.execute(
                        sa.select(t.credentials).where(
                            t.credentials.c.tenant_id == "ten_e2e_oauth"
                        )
                    )
                )
                .mappings()
                .all()
            ]
        assert (
            pick_provider_credential(rows, kill_switch=False)
            == "oauth_subscription"
        )
    finally:
        await engine.dispose()
