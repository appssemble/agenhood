from __future__ import annotations

import control_plane.tables as t


def test_credentials_has_oauth_columns() -> None:
    cols = set(t.credentials.c.keys())
    assert {
        "auth_method",
        "access_token_ciphertext",
        "refresh_token_ciphertext",
        "token_expires_at",
        "oauth_metadata",
        "status",
    } <= cols
    assert t.credentials.c.key_ciphertext.nullable is True
    assert t.credentials.c.key_last4.nullable is True


def test_oauth_connections_table_shape() -> None:
    cols = set(t.oauth_connections.c.keys())
    assert {
        "id",
        "tenant_id",
        "provider",
        "device_code_ciphertext",
        "status",
        "error",
        "credential_id",
        "created_at",
        "expires_at",
    } <= cols
    assert t.oauth_connections.c.device_code_ciphertext.nullable is False
    assert t.oauth_connections.c.expires_at.nullable is False
    assert t.oauth_connections.c.created_at.nullable is False
