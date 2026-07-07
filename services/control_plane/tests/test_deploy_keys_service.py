"""Pure helpers for tenant-scoped skill deploy keys."""
import pytest

from control_plane.ids import new_deploy_key_id
from control_plane.models_db import deploy_keys, skills

pytestmark = pytest.mark.unit


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
