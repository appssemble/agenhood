from __future__ import annotations

from control_plane.config import Settings


def test_oauth_defaults() -> None:
    s = Settings.from_env()
    assert s.oauth_subscription_kill_switch is False
    assert s.oauth_subscription_grace_seconds == 300
    assert s.oauth_poll_sweep_interval_seconds == 5
    assert s.oauth_poll_max_interval_seconds == 120
    assert s.oauth_connection_sweep_interval_seconds == 3600
    assert s.openai_oauth_client_id  # non-empty
    assert "offline_access" in s.openai_oauth_scopes
    assert s.openai_oauth_token_url.startswith("https://")
    assert s.openai_oauth_refresh_url.startswith("https://")
    assert s.openai_oauth_verification_uri.startswith("https://")
    assert s.openai_oauth_redirect_uri == "https://auth.openai.com/deviceauth/callback"


def test_oauth_kill_switch_env_override(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_SUBSCRIPTION_KILL_SWITCH", "true")
    assert Settings.from_env().oauth_subscription_kill_switch is True
