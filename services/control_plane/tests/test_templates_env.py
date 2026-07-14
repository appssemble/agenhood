from __future__ import annotations

import os

import pytest

from control_plane.env_vars import store_env_vars
from control_plane.errors import APIError
from control_plane.routers.templates import template_env_from_body, template_public_view

pytestmark = pytest.mark.unit

_KEY = os.urandom(32)


def _loader() -> bytes:
    return _KEY


def test_public_view_masks_env_secrets() -> None:
    stored = store_env_vars(
        [{"name": "KEY", "value": "s", "secret": True},
         {"name": "URL", "value": "https://x", "secret": False}],
        None, _loader,
    )
    view = template_public_view({"driver": "vanilla", "env_vars": stored})
    assert view["env_vars"] == [
        {"name": "KEY", "value": None, "secret": True},
        {"name": "URL", "value": "https://x", "secret": False},
    ]
    assert "ciphertext" not in str(view["env_vars"])


def test_public_view_without_env_is_empty_list() -> None:
    view = template_public_view({"driver": "vanilla"})
    assert view["env_vars"] == []


def test_env_from_body_create_encrypts(monkeypatch) -> None:
    import control_plane.routers.templates as tpl_mod
    monkeypatch.setattr(tpl_mod, "load_key_from_env", _loader)
    stored = template_env_from_body(
        [{"name": "KEY", "value": "s", "secret": True}], existing=None
    )
    assert stored is not None and "ciphertext" in stored[0]


def test_env_from_body_patch_keeps_existing_secret(monkeypatch) -> None:
    import control_plane.routers.templates as tpl_mod
    monkeypatch.setattr(tpl_mod, "load_key_from_env", _loader)
    existing = store_env_vars([{"name": "KEY", "value": "old", "secret": True}], None, _loader)
    stored = template_env_from_body(
        [{"name": "KEY", "value": None, "secret": True}], existing=existing
    )
    assert stored[0]["ciphertext"] == existing[0]["ciphertext"]


def test_env_from_body_none_passthrough() -> None:
    assert template_env_from_body(None, existing=None) is None


def test_env_from_body_bad_shape_is_400() -> None:
    with pytest.raises(APIError):
        template_env_from_body("not-a-list", existing=None)
