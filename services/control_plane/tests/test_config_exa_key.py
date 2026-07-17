# services/control_plane/tests/test_config_exa_key.py
"""EXA_API_KEY flows into agent containers via Settings.agent_extra_env."""
import pytest

from control_plane.config import Settings

pytestmark = pytest.mark.unit


def _base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")


def test_exa_key_absent_by_default(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EXTRA_ENV", raising=False)
    s = Settings.from_env()
    assert "EXA_API_KEY" not in s.agent_extra_env


def test_exa_key_injected_into_agent_extra_env(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", "exa-secret")
    monkeypatch.delenv("AGENT_EXTRA_ENV", raising=False)
    s = Settings.from_env()
    assert s.agent_extra_env["EXA_API_KEY"] == "exa-secret"


def test_explicit_agent_extra_env_wins_over_exa_var(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", "deploy-key")
    monkeypatch.setenv("AGENT_EXTRA_ENV", "EXA_API_KEY=operator-key")
    s = Settings.from_env()
    assert s.agent_extra_env["EXA_API_KEY"] == "operator-key"
