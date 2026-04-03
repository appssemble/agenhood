import os

import pytest

from connectors.connections_service import (
    build_connection_row,
    decrypt_access_token,
    decrypt_cp_api_key,
    public_connection_view,
)

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


def test_build_row_encrypts_secrets():
    row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T123",
        display_name="Acme", access_token="xoxb-abc", refresh_token=None,
        token_expires_at=None, cp_api_key="tk_live_xyz", scopes="chat:write",
        metadata={"bot_user_id": "U1"}, master_key=KEY,
    )
    assert row["access_token_ciphertext"] != b"xoxb-abc"
    assert decrypt_access_token(row, KEY) == "xoxb-abc"
    assert decrypt_cp_api_key(row, KEY) == "tk_live_xyz"


def test_public_view_hides_secrets():
    row = build_connection_row(
        tenant_id="ten_1", provider="slack", external_id="T123",
        display_name="Acme", access_token="xoxb-abcd1234", refresh_token=None,
        token_expires_at=None, cp_api_key="tk_live_xyz", scopes="chat:write",
        metadata={}, master_key=KEY,
    )
    view = public_connection_view(row)
    assert "access_token_ciphertext" not in view
    assert "cp_api_key_ciphertext" not in view
    assert view["token_last4"] == "1234"
    assert view["provider"] == "slack"
    assert view["status"] == "active"
