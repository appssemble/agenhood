import pytest

from connectors.config import Settings

pytestmark = pytest.mark.unit


def test_from_env_defaults(monkeypatch):
    monkeypatch.delenv("CONNECTORS_DATABASE_URL", raising=False)
    s = Settings.from_env()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.control_plane_base_url  # non-empty default
    assert s.relay_coalesce_ms == 1000


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_BASE_URL", "http://cp:8000")
    monkeypatch.setenv("RELAY_COALESCE_MS", "250")
    s = Settings.from_env()
    assert s.control_plane_base_url == "http://cp:8000"
    assert s.relay_coalesce_ms == 250
