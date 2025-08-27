import pytest
from fastapi import HTTPException

from shim.auth import TokenAuth

pytestmark = pytest.mark.unit


def test_accepts_matching_bearer():
    auth = TokenAuth(token="secret")
    # Should not raise.
    auth.check("Bearer secret")


def test_rejects_wrong_token():
    auth = TokenAuth(token="secret")
    with pytest.raises(HTTPException) as exc:
        auth.check("Bearer nope")
    assert exc.value.status_code == 401


def test_rejects_missing_header():
    auth = TokenAuth(token="secret")
    with pytest.raises(HTTPException) as exc:
        auth.check(None)
    assert exc.value.status_code == 401


def test_empty_token_disables_auth():
    # When no SHIM_TOKEN is configured (local dev), auth is a no-op.
    auth = TokenAuth(token="")
    auth.check(None)
