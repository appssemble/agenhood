from control_plane.auth.passwords import hash_password, verify_password


def test_hash_is_not_plaintext():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert h.startswith("$argon2id$")


def test_verify_accepts_correct_password():
    h = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("s3cret-pw")
    assert verify_password("not-the-password", h) is False


def test_two_hashes_of_same_password_differ():
    # Argon2 salts per-call; identical input must not produce identical hashes.
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_garbage_hash():
    assert verify_password("anything", "not-a-real-hash") is False
