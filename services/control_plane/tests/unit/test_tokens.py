from control_plane.auth.tokens import (
    API_KEY_PREFIX_LEN,
    generate_api_key,
    generate_session_token,
    hash_token,
)


def test_session_token_is_long_and_unique():
    a = generate_session_token()
    b = generate_session_token()
    assert a != b
    assert len(a) >= 43            # 256 bits, urlsafe-base64, no padding


def test_hash_token_is_deterministic_sha256_hex():
    t = "abc"
    assert hash_token(t) == hash_token(t)
    assert len(hash_token(t)) == 64          # sha256 hex
    assert hash_token(t) != t


def test_api_key_has_live_prefix_and_returns_prefix():
    secret, prefix = generate_api_key()
    assert secret.startswith("tk_live_")
    assert prefix == secret[:API_KEY_PREFIX_LEN]
    assert len(prefix) == API_KEY_PREFIX_LEN


def test_api_keys_are_unique():
    s1, _ = generate_api_key()
    s2, _ = generate_api_key()
    assert s1 != s2
