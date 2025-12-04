from __future__ import annotations

import httpx
import pytest
import respx

from control_plane.anthropic_oauth import (
    build_authorize_url,
    exchange_code,
    gen_pkce,
    refresh_access_token,
)
from control_plane.config import Settings
from control_plane.openai_oauth import DeviceFlowError

pytestmark = pytest.mark.unit


def _s() -> Settings:
    return Settings.from_env()


def test_gen_pkce_shape() -> None:
    v, c = gen_pkce()
    assert 43 <= len(v) <= 128
    assert "=" not in v and "=" not in c        # url-safe, unpadded
    assert v != c                                # challenge is the S256 hash


def test_build_authorize_url_has_pkce_and_state() -> None:
    url = build_authorize_url(_s(), state="st8", code_challenge="chal")
    assert url.startswith("https://claude.ai/oauth/authorize?")
    for frag in ("response_type=code", "code_challenge=chal",
                 "code_challenge_method=S256", "state=st8",
                 "client_id=9d1c250a", "scope=user"):
        assert frag in url


@respx.mock
@pytest.mark.asyncio
async def test_exchange_code_returns_tokens() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={
            "access_token": "sk-ant-oat01-acc", "refresh_token": "sk-ant-ort01-ref",
            "expires_in": 28800, "account": {"uuid": "acct-xyz"},
        })
    )
    out = await exchange_code(s, code="c", code_verifier="v", state="st")
    assert out["access_token"] == "sk-ant-oat01-acc"
    assert out["refresh_token"] == "sk-ant-ort01-ref"
    assert out["account_id"] == "acct-xyz"
    assert out["expires_in"] == 28800


@respx.mock
@pytest.mark.asyncio
async def test_exchange_code_error_raises() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(DeviceFlowError):
        await exchange_code(s, code="c", code_verifier="v", state="st")


@respx.mock
@pytest.mark.asyncio
async def test_refresh_rotates_refresh_token() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={
            "access_token": "new-acc", "refresh_token": "new-rot-ref", "expires_in": 28800,
        })
    )
    out = await refresh_access_token(s, "old-ref")
    assert out["access_token"] == "new-acc"
    assert out["refresh_token"] == "new-rot-ref"   # rotated, NOT the old one


@respx.mock
@pytest.mark.asyncio
async def test_refresh_keeps_old_token_if_none_returned() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "expires_in": 28800})
    )
    out = await refresh_access_token(s, "old-ref")
    assert out["refresh_token"] == "old-ref"


@respx.mock
@pytest.mark.asyncio
async def test_refresh_4xx_is_permanent() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(DeviceFlowError):
        await refresh_access_token(s, "old-ref")


@respx.mock
@pytest.mark.asyncio
async def test_exchange_code_malformed_200_raises() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={"expires_in": 28800})  # no access_token
    )
    with pytest.raises(DeviceFlowError):
        await exchange_code(s, code="c", code_verifier="v", state="st")


@respx.mock
@pytest.mark.asyncio
async def test_exchange_code_account_id_from_organization_id() -> None:
    s = _s()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={
            "access_token": "a", "refresh_token": "r", "expires_in": 28800,
            "organization": {"id": "org-77"},
        })
    )
    out = await exchange_code(s, code="c", code_verifier="v", state="st")
    assert out["account_id"] == "org-77"
