"""ConfigPatch.hot_spare round-trips into AgentConfig and defaults to on."""
from control_plane.schemas import ConfigPatch


def test_patch_hot_spare_defaults_to_on():
    assert ConfigPatch(driver="codex", model="gpt-5.4").to_agent_config().hot_spare is True


def test_patch_hot_spare_off_flows_into_agent_config():
    patch = ConfigPatch(driver="codex", model="gpt-5.4", hot_spare=False)
    assert patch.to_agent_config().hot_spare is False


def test_hot_spare_on_is_valid_for_any_driver():
    from agentcore.models import AgentConfig
    from control_plane.config_validation import validate_config

    validate_config(AgentConfig(driver="vanilla", model="claude-opus-4-7"),
                    {"allowed_drivers": ["vanilla"]})
