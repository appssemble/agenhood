import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from connectors.crypto import decrypt_secret, encrypt_secret, load_key_from_env

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


def test_round_trip():
    blob = encrypt_secret("xoxb-secret", KEY)
    assert isinstance(blob, bytes)
    assert decrypt_secret(blob, KEY) == "xoxb-secret"


def test_tamper_raises():
    blob = bytearray(encrypt_secret("hello", KEY))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        decrypt_secret(bytes(blob), KEY)


def test_wrong_key_length_raises():
    with pytest.raises(ValueError):
        encrypt_secret("x", b"short")


def test_load_key_from_env(monkeypatch):
    monkeypatch.setenv("CONNECTORS_MASTER_KEY", base64.b64encode(KEY).decode())
    assert load_key_from_env() == KEY
