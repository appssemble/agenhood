from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from control_plane.config import Settings
from control_plane.openai_oauth import (
    DeviceFlowError,
    DeviceFlowPending,
    exchange_device_code,
    extract_account_id,
    refresh_access_token,
    start_device_flow,
)


def _settings() -> Settings:
    return Settings.from_env()


def _jwt(payload: dict) -> str:
    def seg(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'none'})}.{seg(payload)}.sig"


def test_extract_account_id_root_claim() -> None:
    tok = _jwt({"chatgpt_account_id": "acct_root"})
    assert extract_account_id(tok) == "acct_root"


def test_extract_account_id_nested_auth_claim() -> None:
    tok = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_nested"}})
    assert extract_account_id(tok) == "acct_nested"


def test_extract_account_id_orgs_fallback() -> None:
    tok = _jwt({"organizations": [{"id": "org_first"}]})
    assert extract_account_id(tok) == "org_first"


def test_extract_account_id_none_when_absent() -> None:
    assert extract_account_id(_jwt({"sub": "x"})) is None


@respx.mock
@pytest.mark.asyncio
async def test_start_device_flow() -> None:
    s = _settings()
    respx.post(s.openai_oauth_device_code_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_auth_id": "da_1",
                "user_code": "WXYZ-1234",
                "interval": "5",
                "expires_at": "2030-01-01T00:00:00+00:00",
            },
        )
    )
    out = await start_device_flow(s)
    assert out["device_auth_id"] == "da_1"
    assert out["user_code"] == "WXYZ-1234"
    assert out["interval"] == 5
    assert out["verification_uri"] == s.openai_oauth_verification_uri
    assert out["expires_in"] > 0
    assert "verification_uri_complete" not in out
    assert "device_code" not in out


@respx.mock
@pytest.mark.asyncio
async def test_exchange_pending_raises() -> None:
    s = _settings()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(
            403, json={"error": {"code": "deviceauth_authorization_pending"}}
        )
    )
    with pytest.raises(DeviceFlowPending):
        await exchange_device_code(s, "da_1", "WXYZ-1234")


@respx.mock
@pytest.mark.asyncio
async def test_exchange_denied_raises_error() -> None:
    s = _settings()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(403, json={"error": {"code": "access_denied"}})
    )
    with pytest.raises(DeviceFlowError):
        await exchange_device_code(s, "da_1", "WXYZ-1234")


@respx.mock
@pytest.mark.asyncio
async def test_exchange_success_returns_tokens() -> None:
    s = _settings()
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
                "access_token": "acc-1",
                "refresh_token": "ref-1",
                "id_token": _jwt({"chatgpt_account_id": "acct_1"}),
                "expires_in": 3600,
            },
        )
    )
    out = await exchange_device_code(s, "da_1", "WXYZ-1234")
    assert out["access_token"] == "acc-1"
    assert out["refresh_token"] == "ref-1"
    assert out["account_id"] == "acct_1"
    assert out["expires_in"] == 3600


@respx.mock
@pytest.mark.asyncio
async def test_redeem_uses_device_redirect_uri() -> None:
    s = _settings()
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
    route = respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc-1",
                "refresh_token": "ref-1",
                "id_token": _jwt({"chatgpt_account_id": "acct_1"}),
                "expires_in": 3600,
            },
        )
    )
    await exchange_device_code(s, "da_1", "WXYZ-1234")
    body = route.calls.last.request.content.decode()
    assert "grant_type=authorization_code" in body
    from urllib.parse import parse_qs

    form = parse_qs(body)
    assert form["redirect_uri"] == [s.openai_oauth_redirect_uri]


@respx.mock
@pytest.mark.asyncio
async def test_refresh_access_token() -> None:
    s = _settings()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(
            200, json={"access_token": "acc-2", "refresh_token": "ref-2", "expires_in": 3600}
        )
    )
    out = await refresh_access_token(s, "ref-1")
    assert out["access_token"] == "acc-2"
    assert out["refresh_token"] == "ref-2"
    assert out["expires_in"] == 3600


@respx.mock
@pytest.mark.asyncio
async def test_refresh_invalid_grant_raises_error() -> None:
    s = _settings()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(DeviceFlowError):
        await refresh_access_token(s, "ref-bad")


@respx.mock
@pytest.mark.asyncio
async def test_exchange_slow_down_sets_flag() -> None:
    s = _settings()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(429, json={"error": {"code": "slow_down"}})
    )
    with pytest.raises(DeviceFlowPending) as exc:
        await exchange_device_code(s, "da_1", "WXYZ-1234")
    assert exc.value.slow_down is True


@respx.mock
@pytest.mark.asyncio
async def test_exchange_malformed_200_raises_error() -> None:
    s = _settings()
    respx.post(s.openai_oauth_token_url).mock(
        return_value=httpx.Response(
            200, json={"authorization_code": "ac_1", "code_verifier": "cv_1"}
        )
    )
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    with pytest.raises(DeviceFlowError):
        await exchange_device_code(s, "da_1", "WXYZ-1234")


@respx.mock
@pytest.mark.asyncio
async def test_refresh_keeps_old_refresh_token_when_absent() -> None:
    s = _settings()
    respx.post(s.openai_oauth_refresh_url).mock(
        return_value=httpx.Response(200, json={"access_token": "acc-2", "expires_in": 3600})
    )
    out = await refresh_access_token(s, "ref-keep")
    assert out["access_token"] == "acc-2"
    assert out["refresh_token"] == "ref-keep"


def test_event_bus_register_publish_unregister() -> None:
    from control_plane.oauth_events import OAuthEventBus

    bus = OAuthEventBus()
    q = bus.register("conn-1")
    bus.publish("conn-1", "connected")
    assert q.get_nowait() == "connected"
    # publish to an unknown/unregistered id is a no-op (does not raise)
    bus.unregister("conn-1")
    bus.publish("conn-1", "ignored")
    bus.publish("conn-unknown", "ignored")
