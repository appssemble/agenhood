import os
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from connectors.providers.github import GitHubProvider

pytestmark = pytest.mark.unit


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_app_jwt_is_valid():
    pem = _pem()
    p = GitHubProvider(app_id="123", private_key_pem=pem, webhook_secret="x")
    token = p._app_jwt()
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "123"
    assert decoded["exp"] > time.time()


@pytest.mark.asyncio
async def test_mint_installation_token(monkeypatch):
    pem = _pem()
    p = GitHubProvider(app_id="123", private_key_pem=pem, webhook_secret="x")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/access_tokens")
        return httpx.Response(201, json={"token": "ghs_installtoken"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(p, "_transport", transport, raising=False)
    row = {"external_id": "inst_55", "connection_metadata": {}}
    token = await p.mint_token(row, master_key=os.urandom(32))
    assert token == "ghs_installtoken"


@pytest.mark.asyncio
async def test_post_and_update_comment():
    pem = _pem()
    p = GitHubProvider(app_id="123", private_key_pem=pem, webhook_secret="x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"id": 99})
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": 99})
        return httpx.Response(404)

    p._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    origin_ref = {"repo": "org/repo", "number": 1}
    handle = await p.post_initial("tok", origin_ref, "hello")
    assert handle == {"repo": "org/repo", "comment_id": 99}
    await p.update_message("tok", handle, "updated")
