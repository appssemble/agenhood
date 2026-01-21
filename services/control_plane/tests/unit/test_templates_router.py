import pytest

pytestmark = pytest.mark.unit


def test_template_list_response_is_wrapped_and_has_driver_metadata():
    # Use the route helper directly with fake rows/registries: the API contract is
    # {"templates": [...]}, and each row carries capabilities/template/tool specs
    # for the console editor. This test must fail if the backend returns a bare list.
    from control_plane.routers.templates import response_list, template_public_view

    row = {
        "id": "tpl_1", "tenant_id": None, "name": "Vanilla", "driver": "vanilla",
        "model": "claude-opus-4-7", "system_prompt": "", "system_prompt_mode": "augment",
        "tools": ["read_file"], "context": {}, "limits": {}, "is_builtin": True,
    }
    out = response_list([template_public_view(row)])
    assert set(out) == {"templates"}
    assert out["templates"][0]["driver_template"]["driver"] == "vanilla"
    assert "available_tool_specs" in out["templates"][0]


def test_builtin_template_cannot_be_patched_or_deleted():
    from control_plane.errors import APIError
    from control_plane.routers.templates import ensure_mutable_template

    with pytest.raises(APIError) as exc:
        ensure_mutable_template({"id": "tpl_builtin", "tenant_id": None, "is_builtin": True})
    assert exc.value.code == "validation_error"
    assert exc.value.field == "id"
