from __future__ import annotations

import base64
import os

import pytest

from control_plane.auth.crypto import decrypt_secret
from control_plane.env_vars import (
    MAX_ENV_VARS,
    public_env_vars,
    resolve_env,
    store_env_vars,
)
from control_plane.errors import APIError

pytestmark = pytest.mark.unit

_KEY = os.urandom(32)


def _loader() -> bytes:
    return _KEY


def _failing_loader() -> bytes:
    raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not set")


# ---- store_env_vars: validation ---------------------------------------------

def test_plain_var_stored_verbatim() -> None:
    stored = store_env_vars(
        [{"name": "MY_URL", "value": "https://x", "secret": False}], None, _loader
    )
    assert stored == [{"name": "MY_URL", "value": "https://x", "secret": False}]


@pytest.mark.parametrize("bad", ["lower", "1LEADING", "WITH-DASH", "WITH SPACE", ""])
def test_bad_name_rejected(bad: str) -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": bad, "value": "v", "secret": False}], None, _loader)
    assert exc.value.status_code == 400
    assert exc.value.code == "validation_error"
    assert exc.value.field == "env_vars[0].name"


def test_non_string_name_rejected() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": 123, "value": "v", "secret": False}], None, _loader)
    assert exc.value.status_code == 400
    assert exc.value.code == "validation_error"
    assert exc.value.field == "env_vars[0].name"


def test_non_string_value_rejected() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": "OK", "value": 123, "secret": False}], None, _loader)
    assert exc.value.status_code == 400
    assert exc.value.code == "validation_error"
    assert exc.value.field == "env_vars[0].value"


def test_name_too_long_rejected() -> None:
    with pytest.raises(APIError):
        store_env_vars([{"name": "A" * 129, "value": "v", "secret": False}], None, _loader)


@pytest.mark.parametrize(
    "reserved",
    ["SHIM_TOKEN", "HOME", "PATH", "HTTP_PROXY", "NO_PROXY", "TENANT_ID", "EXA_API_KEY"],
)
def test_reserved_name_rejected(reserved: str) -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": reserved, "value": "v", "secret": False}], None, _loader)
    assert exc.value.field == "env_vars[0].name"


def test_duplicate_name_rejected() -> None:
    items = [
        {"name": "DUP", "value": "a", "secret": False},
        {"name": "DUP", "value": "b", "secret": False},
    ]
    with pytest.raises(APIError) as exc:
        store_env_vars(items, None, _loader)
    assert exc.value.field == "env_vars[1].name"


def test_value_too_long_rejected() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": "BIG", "value": "x" * 8193, "secret": False}], None, _loader)
    assert exc.value.field == "env_vars[0].value"


def test_too_many_vars_rejected() -> None:
    items = [{"name": f"V{i}", "value": "x", "secret": False} for i in range(MAX_ENV_VARS + 1)]
    with pytest.raises(APIError) as exc:
        store_env_vars(items, None, _loader)
    assert exc.value.field == "env_vars"


def test_plain_var_requires_value() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": "NOVALUE", "value": None, "secret": False}], None, _loader)
    assert exc.value.field == "env_vars[0].value"


# ---- store_env_vars: secrets -------------------------------------------------

def test_secret_encrypted_round_trip() -> None:
    stored = store_env_vars([{"name": "KEY", "value": "s3cret", "secret": True}], None, _loader)
    assert stored[0]["secret"] is True
    assert "value" not in stored[0]
    blob = base64.b64decode(stored[0]["ciphertext"])
    assert decrypt_secret(blob, _KEY) == "s3cret"


def test_secret_null_keeps_existing_ciphertext() -> None:
    existing = store_env_vars([{"name": "KEY", "value": "old", "secret": True}], None, _loader)
    stored = store_env_vars([{"name": "KEY", "value": None, "secret": True}], existing, _loader)
    assert stored[0]["ciphertext"] == existing[0]["ciphertext"]


def test_secret_null_with_no_existing_rejected() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": "KEY", "value": None, "secret": True}], None, _loader)
    assert exc.value.status_code == 400
    assert exc.value.field == "env_vars[0].value"


def test_omitted_item_is_deleted_full_replace() -> None:
    existing = store_env_vars(
        [
            {"name": "A", "value": "1", "secret": False},
            {"name": "B", "value": "2", "secret": False},
        ],
        None, _loader,
    )
    stored = store_env_vars([{"name": "A", "value": "1", "secret": False}], existing, _loader)
    assert [i["name"] for i in stored] == ["A"]


def test_missing_key_is_encryption_unavailable() -> None:
    with pytest.raises(APIError) as exc:
        store_env_vars([{"name": "KEY", "value": "s", "secret": True}], None, _failing_loader)
    assert exc.value.status_code == 500
    assert exc.value.code == "encryption_unavailable"


def test_plain_vars_never_touch_the_key() -> None:
    # No secret in the payload → key_loader must not be called at all.
    stored = store_env_vars([{"name": "A", "value": "1", "secret": False}], None, _failing_loader)
    assert stored[0]["value"] == "1"


# ---- public_env_vars -----------------------------------------------------------

def test_public_view_masks_secrets() -> None:
    stored = store_env_vars(
        [{"name": "URL", "value": "https://x", "secret": False},
         {"name": "KEY", "value": "s", "secret": True}],
        None, _loader,
    )
    assert public_env_vars(stored) == [
        {"name": "URL", "value": "https://x", "secret": False},
        {"name": "KEY", "value": None, "secret": True},
    ]


def test_public_view_of_none_is_empty() -> None:
    assert public_env_vars(None) == []


# ---- resolve_env ----------------------------------------------------------------

def test_resolve_env_decrypts_secrets() -> None:
    stored = store_env_vars(
        [{"name": "URL", "value": "https://x", "secret": False},
         {"name": "KEY", "value": "s3cret", "secret": True}],
        None, _loader,
    )
    assert resolve_env(stored, _loader) == {"URL": "https://x", "KEY": "s3cret"}


def test_resolve_env_of_none_is_empty() -> None:
    assert resolve_env(None, _loader) == {}


def test_resolve_env_missing_key_is_encryption_unavailable() -> None:
    stored = store_env_vars([{"name": "KEY", "value": "s", "secret": True}], None, _loader)
    with pytest.raises(APIError) as exc:
        resolve_env(stored, _failing_loader)
    assert exc.value.status_code == 500
    assert exc.value.code == "encryption_unavailable"


def test_resolve_env_corrupt_ciphertext_is_encryption_unavailable() -> None:
    stored = [{"name": "KEY", "secret": True, "ciphertext": base64.b64encode(b"garbage").decode()}]
    with pytest.raises(APIError) as exc:
        resolve_env(stored, _loader)
    assert exc.value.code == "encryption_unavailable"
