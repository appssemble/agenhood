# services/shim/tests/integration/container/test_auth.py
#
# SHIM_TOKEN enforcement: every protected route calls auth.check().
# Shape confirmed in shim/auth.py: TokenAuth.check always raises
# HTTPException(status_code=401) — for both missing bearer and wrong token.
#
# Raw httpx (not the pre-authed `client` fixture) so we control the header.
# `stack` fixture (not `client`) ensures the docker stack is up without
# injecting the correct Authorization header.
import httpx
import pytest

from .conftest import BASE, TOKEN

pytestmark = pytest.mark.integration


def test_missing_bearer_rejected(stack):
    # No Authorization header → 401 ("missing bearer token")
    r = httpx.get(f"{BASE}/tasks", timeout=10)
    assert r.status_code == 401


def test_wrong_bearer_rejected(stack):
    # Wrong bearer value → 401 ("invalid token")
    r = httpx.get(
        f"{BASE}/tasks",
        headers={"Authorization": "Bearer wrong-token"},
        timeout=10,
    )
    assert r.status_code == 401


def test_correct_bearer_accepted(stack):
    # Correct SHIM_TOKEN → 200 with task list
    r = httpx.get(
        f"{BASE}/tasks",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=10,
    )
    assert r.status_code == 200
