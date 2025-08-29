"""Task 13: Unit tests for validate_config_against_tenant (tenant allowed_drivers/models)."""
import pytest

from agentcore.models import AgentConfig
from control_plane.config_validation import ConfigInvalid, validate_config_against_tenant

TENANT = {
    "allowed_drivers": ["vanilla"],
}


def _cfg(**kw: object) -> AgentConfig:
    base: dict[str, object] = dict(driver="vanilla", model="claude-opus-4-7", tools=[])
    base.update(kw)
    return AgentConfig(**base)  # type: ignore[arg-type]


def test_allowed_driver_and_model_pass():
    validate_config_against_tenant(_cfg(), TENANT)  # no raise


def test_disallowed_driver_rejected():
    with pytest.raises(ConfigInvalid) as e:
        validate_config_against_tenant(_cfg(driver="opencode"), TENANT)
    assert e.value.field == "driver"


def test_model_not_in_catalog_rejected():
    # Model unknown to catalog is rejected regardless of tenant driver allowlist.
    with pytest.raises(ConfigInvalid) as e:
        validate_config_against_tenant(_cfg(model="not-a-real-model-xyz"), TENANT)
    assert e.value.field == "model"


def test_model_not_supported_by_driver_rejected():
    # openai models only support opencode driver; vanilla driver → rejected.
    with pytest.raises(ConfigInvalid) as e:
        validate_config_against_tenant(
            _cfg(model="gpt-5.4"),
            {"allowed_drivers": ["vanilla", "opencode"]},
        )
    assert e.value.field == "model"
