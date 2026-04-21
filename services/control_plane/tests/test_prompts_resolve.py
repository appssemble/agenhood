import pytest

from control_plane.prompts_service import resolve_body

pytestmark = pytest.mark.unit


def test_resolve_fills_from_values():
    out = resolve_body("Hello {{name}}, welcome to {{city}}.",
                       {"name": "Ada", "city": "Cluj"}, [])
    assert out == "Hello Ada, welcome to Cluj."


def test_resolve_falls_back_to_defaults():
    vars_ = [{"name": "name", "label": "", "default": "there"}]
    assert resolve_body("Hi {{name}}", {}, vars_) == "Hi there"


def test_resolve_value_overrides_default():
    vars_ = [{"name": "name", "default": "there"}]
    assert resolve_body("Hi {{name}}", {"name": "Ada"}, vars_) == "Hi Ada"


def test_resolve_leaves_unknown_placeholder_verbatim():
    assert resolve_body("Hi {{name}} from {{city}}", {"name": "Ada"}, []) \
        == "Hi Ada from {{city}}"


def test_resolve_empty_value_leaves_placeholder():
    # Explicit empty value overrides default and (like the console) leaves the
    # placeholder rather than substituting "".
    vars_ = [{"name": "name", "default": "there"}]
    assert resolve_body("Hi {{name}}", {"name": ""}, vars_) == "Hi {{name}}"


def test_resolve_whitespace_tolerant():
    assert resolve_body("{{ name }}", {"name": "Ada"}, []) == "Ada"


def test_resolve_no_variables_passthrough():
    assert resolve_body("plain text", {}, []) == "plain text"


def test_resolve_handles_none_args():
    assert resolve_body("Hi {{name}}", None, None) == "Hi {{name}}"
