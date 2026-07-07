"""Pure helpers for tenant-scoped skill deploy keys."""
import base64

import pytest

from control_plane.auth.crypto import decrypt_secret
from control_plane.deploy_keys_service import (
    build_deploy_key_row,
    decrypt_deploy_key,
    deploy_key_public_view,
)
from control_plane.ids import new_deploy_key_id
from control_plane.models_db import deploy_keys, skills

pytestmark = pytest.mark.unit

_MASTER = base64.b64decode(base64.b64encode(b"B" * 32))


def test_new_deploy_key_id_prefix():
    a, b = new_deploy_key_id(), new_deploy_key_id()
    assert a.startswith("dk_") and b.startswith("dk_") and a != b


def test_deploy_keys_table_shape():
    cols = {c.name for c in deploy_keys.columns}
    assert {"id", "tenant_id", "name", "ssh_private_key_ciphertext",
            "ssh_public_key", "key_type", "key_fingerprint",
            "created_at", "updated_at"} <= cols


def test_skills_has_deploy_key_fk():
    assert "deploy_key_id" in {c.name for c in skills.columns}


def test_build_row_roundtrip_and_shape():
    row = build_deploy_key_row(tenant_id="ten_x", name="team-skills", master_key=_MASTER)
    assert row["id"].startswith("dk_")
    assert row["tenant_id"] == "ten_x" and row["name"] == "team-skills"
    assert row["key_type"] == "ed25519"
    assert row["ssh_public_key"].startswith("ssh-ed25519 ")
    assert row["key_fingerprint"].startswith("SHA256:")
    priv = decrypt_secret(row["ssh_private_key_ciphertext"], _MASTER)
    assert "OPENSSH PRIVATE KEY" in priv
    assert decrypt_deploy_key(row, _MASTER) == priv


def test_build_row_rejects_blank_name():
    with pytest.raises(ValueError):
        build_deploy_key_row(tenant_id="ten_x", name="  ", master_key=_MASTER)


def test_public_view_never_leaks_private_key():
    row = build_deploy_key_row(tenant_id="ten_x", name="k", master_key=_MASTER)
    view = deploy_key_public_view(row)
    assert set(view) == {"id", "name", "ssh_public_key", "key_type",
                         "key_fingerprint", "created_at", "updated_at"}
    assert "ciphertext" not in repr(view).lower()
