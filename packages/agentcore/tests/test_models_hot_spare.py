"""AgentConfig.hot_spare: on by default, old snapshots still parse."""
from agentcore.models import AgentConfig


def test_hot_spare_defaults_to_on():
    assert AgentConfig(driver="codex", model="gpt-5.6-sol").hot_spare is True


def test_old_config_snapshot_without_hot_spare_parses():
    cfg = AgentConfig(**{"driver": "codex", "model": "gpt-5.6-sol"})
    assert cfg.model_dump()["hot_spare"] is True


def test_hot_spare_can_be_turned_off():
    assert AgentConfig(driver="codex", model="m", hot_spare=False).hot_spare is False
