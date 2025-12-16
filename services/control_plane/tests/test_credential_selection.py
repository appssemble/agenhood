from __future__ import annotations

from datetime import UTC, datetime, timedelta

from control_plane.routers.tasks import pick_provider_credential


def _row(auth_method: str, status: str = "active", ttl_seconds: int = 7200):
    return {
        "id": f"cred_{auth_method}",
        "auth_method": auth_method,
        "status": status,
        "token_expires_at": datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    }


def test_prefers_active_oauth() -> None:
    rows = [_row("api_key"), _row("oauth_subscription")]
    assert pick_provider_credential(rows, kill_switch=False) == "oauth_subscription"


def test_oauth_chosen_even_when_stored_token_is_stale() -> None:
    # The stored access token is expired, but the credential is active and has a
    # refresh token, so the picker still selects it — ensure_fresh_oauth refreshes
    # it and the long-task TTL rule is enforced on the fresh token in the submit
    # path. (Regression: previously this fell back / failed with "no usable
    # credential" when only a stale subscription existed.)
    rows = [_row("oauth_subscription", ttl_seconds=-3600)]
    assert pick_provider_credential(rows, kill_switch=False) == "oauth_subscription"


def test_falls_back_when_oauth_reauth_required() -> None:
    rows = [_row("api_key"), _row("oauth_subscription", status="reauth_required")]
    assert pick_provider_credential(rows, kill_switch=False) == "api_key"


def test_kill_switch_skips_oauth() -> None:
    rows = [_row("api_key"), _row("oauth_subscription")]
    assert pick_provider_credential(rows, kill_switch=True) == "api_key"


def test_kill_switch_with_only_oauth_is_unusable() -> None:
    rows = [_row("oauth_subscription")]
    assert pick_provider_credential(rows, kill_switch=True) is None


def test_returns_none_when_nothing_usable() -> None:
    rows = [_row("oauth_subscription", status="reauth_required")]
    assert pick_provider_credential(rows, kill_switch=False) is None


def test_subscription_skipped_when_driver_cannot_use_it() -> None:
    # e.g. opencode/vanilla + an anthropic subscription: the driver can't consume
    # it, so the picker falls back to an API key rather than handing over a token
    # the driver will reject (which previously surfaced as a 500).
    rows = [_row("api_key"), _row("oauth_subscription")]
    assert pick_provider_credential(
        rows, kill_switch=False, subscription_usable=False
    ) == "api_key"


def test_subscription_unusable_and_no_api_key_returns_none() -> None:
    rows = [_row("oauth_subscription")]
    assert pick_provider_credential(
        rows, kill_switch=False, subscription_usable=False
    ) is None
