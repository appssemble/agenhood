from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12
_KEY_LEN = 32


def encrypt_secret(plaintext: str, key: bytes) -> bytes:
    if len(key) != _KEY_LEN:
        raise ValueError(f"key must be {_KEY_LEN} bytes, got {len(key)}")
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt_secret(blob: bytes, key: bytes) -> str:
    if len(key) != _KEY_LEN:
        raise ValueError(f"key must be {_KEY_LEN} bytes, got {len(key)}")
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")


def load_key_from_env(var: str = "CONNECTORS_MASTER_KEY") -> bytes:
    raw = os.environ.get(var)
    if not raw:
        raise ValueError(f"{var} is not set")
    key = base64.b64decode(raw)
    if len(key) != _KEY_LEN:
        raise ValueError(f"{var} must decode to {_KEY_LEN} bytes, got {len(key)}")
    return key
