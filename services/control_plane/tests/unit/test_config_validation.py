import pytest

from agentcore.models import AgentConfig
from control_plane.config_validation import validate_config
from control_plane.errors import APIError

pytestmark = pytest.mark.unit

LIMITS = {
    "allowed_drivers": ["vanilla", "opencode"],
}


def _vanilla_config(**over: object) -> AgentConfig:
    base: dict[str, object] = dict(
        driver="vanilla",
        model="claude-opus-4-7",
        system_prompt="hi",
        system_prompt_mode="augment",
        tools=["read_file", "write_file"],
    )
    base.update(over)
    return AgentConfig(**base)  # type: ignore[arg-type]


def test_accepts_legal_config() -> None:
    validate_config(_vanilla_config(), LIMITS)  # no raise


def test_rejects_unknown_driver() -> None:
    with pytest.raises(APIError) as ei:
        validate_config(_vanilla_config(driver="nope"), LIMITS)
    assert ei.value.code == "validation_error"
    assert ei.value.field == "driver"


def test_rejects_driver_not_in_allowed() -> None:
    limits = {"allowed_drivers": ["opencode"]}
    with pytest.raises(APIError) as ei:
        validate_config(_vanilla_config(), limits)
    assert ei.value.field == "driver"


def test_rejects_model_not_in_catalog() -> None:
    # Model unknown to catalog → rejected.
    with pytest.raises(APIError) as ei:
        validate_config(_vanilla_config(model="not-a-real-model-xyz"), LIMITS)
    assert ei.value.field == "model"


def test_rejects_tool_not_in_driver_available_tools() -> None:
    with pytest.raises(APIError) as ei:
        validate_config(
            _vanilla_config(tools=["read_file", "definitely_not_a_tool"]), LIMITS
        )
    assert ei.value.field == "tools"


def test_rejects_editing_tools_when_not_editable(monkeypatch: pytest.MonkeyPatch) -> None:
    # opencode owns its tools (tools_user_editable=False). Setting a non-default
    # tools list must be rejected.
    from agentcore.drivers.base import DRIVERS

    if "opencode" not in DRIVERS:
        pytest.skip("opencode driver lands in Unit 3")
    cfg = AgentConfig(driver="opencode", model="claude-opus-4-7", tools=["read_file"])
    with pytest.raises(APIError) as ei:
        validate_config(cfg, LIMITS)
    assert ei.value.field == "tools"


def test_rejects_illegal_prompt_mode() -> None:
    # Pydantic enforces the Literal at model construction; build raw then validate.
    cfg = _vanilla_config()
    object.__setattr__(cfg, "system_prompt_mode", "obliterate")
    with pytest.raises(APIError) as ei:
        validate_config(cfg, LIMITS)
    assert ei.value.field == "system_prompt_mode"
