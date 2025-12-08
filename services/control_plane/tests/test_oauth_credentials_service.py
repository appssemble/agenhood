from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from control_plane.credentials_service import (
    build_oauth_credential_row,
    decrypt_oauth_row,
)


@pytest.fixture
def key() -> bytes:
    return os.urandom(32)


def test_build_oauth_row_encrypts_tokens_and_stores_metadata(key: bytes) -> None:
    expires = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    row = build_oauth_credential_row(
        tenant_id="ten_1",
        provider="openai",
        access_token="access-SECRET-123",
        refresh_token="refresh-SECRET-456",
        token_expires_at=expires,
        account_id="acct_9f3a",
        created_by="usr_1",
        master_key=key,
    )
    assert row["provider"] == "openai"
    assert row["auth_method"] == "oauth_subscription"
    assert row["status"] == "active"
    assert row["token_expires_at"] == expires
    assert row["oauth_metadata"]["account_id"] == "acct_9f3a"
    # Secrets must not appear as plaintext anywhere outside the ciphertext bytes
    # that hold them.
    assert b"access-SECRET-123" not in row["refresh_token_ciphertext"]
    assert b"refresh-SECRET-456" not in row["access_token_ciphertext"]
    # api-key columns are unused for oauth rows
    assert row.get("key_ciphertext") is None
    assert row.get("key_last4") is None


def test_decrypt_oauth_row_round_trip(key: bytes) -> None:
    expires = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    row = build_oauth_credential_row(
        tenant_id="ten_1",
        provider="openai",
        access_token="acc-xyz",
        refresh_token="ref-xyz",
        token_expires_at=expires,
        account_id="acct_1",
        created_by=None,
        master_key=key,
    )
    out = decrypt_oauth_row(row, key)
    assert out == {
        "access_token": "acc-xyz",
        "refresh_token": "ref-xyz",
        "account_id": "acct_1",
        "id_token": None,
        "token_expires_at": expires,
    }


def test_id_token_round_trip_encrypted(key: bytes) -> None:
    expires = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    row = build_oauth_credential_row(
        tenant_id="ten_1",
        provider="openai",
        access_token="acc",
        refresh_token="ref",
        token_expires_at=expires,
        account_id="acct_1",
        created_by=None,
        master_key=key,
        id_token="eyJ-SECRET-IDTOKEN",
    )
    # Stored encrypted (not plaintext) under id_token_ct.
    assert "eyJ-SECRET-IDTOKEN" not in str(row["oauth_metadata"])
    assert "id_token_ct" in row["oauth_metadata"]
    out = decrypt_oauth_row(row, key)
    assert out["id_token"] == "eyJ-SECRET-IDTOKEN"
