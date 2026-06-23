from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings
from control_plane.routers.git import _verify_message, push_record_values

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


# ---- pure-helper unit tests -------------------------------------------------

def test_push_record_values_success() -> None:
    v = push_record_values({"ok": True, "sha": "a" * 40})
    assert v["last_push_status"] == "pushed"
    assert v["last_push_error"] is None


def test_push_record_values_failure() -> None:
    v = push_record_values({"ok": False, "error_code": "push_auth_failed"})
    assert v["last_push_status"] == "failed"
    assert v["last_push_error"] == "push_auth_failed"


def test_verify_message_known_codes() -> None:
    assert "deploy key" in _verify_message("auth_failed")
    assert "unreachable" in _verify_message("host_unreachable")
    assert "not found" in _verify_message("repo_not_found")
    assert "network" in _verify_message("egress_blocked")
    assert "host key" in _verify_message("host_key_changed")


def test_verify_message_unknown_code_returns_generic() -> None:
    assert _verify_message(None) == "could not reach the remote"
    assert _verify_message("unknown_code") == "could not reach the remote"


# ---- 422 response never leaks secrets ---------------------------------------

@pytest.mark.asyncio
async def test_get_remote_hides_keygen_stub() -> None:
    """GET /git/remote must return {"remote": None} when a keygen stub exists
    (url="") — the stub row must not be rendered as a phantom linked remote."""
    from control_plane.routers.git import get_remote

    stub_row = {
        "container_id": "ctr_x",
        "url": "",
        "branch": "main",
        "enabled": False,
        "ssh_public_key": "ssh-ed25519 AAAA...",
        "key_fingerprint": "SHA256:abc",
        "key_type": "ed25519",
        "ssh_private_key_ciphertext": b"enc",
        "last_push_status": None,
        "last_push_error": None,
        "last_push_at": None,
        "verified_at": None,
        "created_at": None,
        "updated_at": None,
    }

    principal = Principal(tenant_id="ten_seed", role="member", is_staff=False, user_id=None)

    with (
        patch("control_plane.routers.git._load_owned_container", new_callable=AsyncMock),
        patch(
            "control_plane.routers.git._load_remote",
            new_callable=AsyncMock, return_value=stub_row,
        ),
    ):
        result = await get_remote(
            cid="ctr_x",
            request=None,  # type: ignore[arg-type]
            principal=principal,
            session=None,  # type: ignore[arg-type]
        )

    assert result == {"remote": None}


async def test_put_remote_422_never_echoes_secrets() -> None:
    """FastAPI's default 422 handler echoes the whole body under
    detail[].input — the app must strip it.  url omitted → body validation
    fails → 422 before the route runs."""
    app = create_app(Settings.from_env())
    app.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id="ten_seed", role="member", is_staff=False, user_id=None
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # `url` omitted -> body validation fails -> 422 before the route runs.
        r = await c.put(
            "/v1/containers/ctr_x/git/remote",
            json={"branch": "main"},
        )

    assert r.status_code == 422
    body = r.json()
    assert any(e["loc"] == ["body", "url"] for e in body["detail"])
    for err in body["detail"]:
        assert "input" not in err
        assert "ctx" not in err
