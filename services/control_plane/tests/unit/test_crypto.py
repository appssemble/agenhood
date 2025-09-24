import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from control_plane.auth.crypto import decrypt_secret, encrypt_secret, load_key_from_env


@pytest.fixture
def key() -> bytes:
    return os.urandom(32)


def test_round_trip(key: bytes) -> None:
    ct = encrypt_secret("sk-ant-supersecret", key)
    assert decrypt_secret(ct, key) == "sk-ant-supersecret"


def test_ciphertext_is_not_plaintext(key: bytes) -> None:
    ct = encrypt_secret("sk-ant-supersecret", key)
    assert b"sk-ant-supersecret" not in ct
    assert b"supersecret" not in ct


def test_ciphertext_differs_each_call_due_to_nonce(key: bytes) -> None:
    a = encrypt_secret("same-secret", key)
    b = encrypt_secret("same-secret", key)
    assert a != b  # 12-byte random nonce prepended


def test_tamper_detection_flipped_byte_raises(key: bytes) -> None:
    ct = bytearray(encrypt_secret("sk-ant-supersecret", key))
    ct[-1] ^= 0x01  # flip one bit of the ciphertext/tag
    with pytest.raises(InvalidTag):
        decrypt_secret(bytes(ct), key)


def test_wrong_key_raises(key: bytes) -> None:
    ct = encrypt_secret("sk-ant-supersecret", key)
    other = os.urandom(32)
    with pytest.raises(InvalidTag):
        decrypt_secret(ct, other)


def test_load_key_from_env_decodes_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.urandom(32)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.b64encode(raw).decode())
    assert load_key_from_env() == raw


def test_load_key_from_env_rejects_wrong_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.b64encode(os.urandom(16)).decode())
    with pytest.raises(ValueError):
        load_key_from_env()
