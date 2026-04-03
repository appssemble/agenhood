import hashlib
import hmac
import time

import httpx
import pytest

from connectors.providers.slack import SlackProvider

pytestmark = pytest.mark.unit
SECRET = "slk_signing"


def _headers(body: bytes, ts: str | None = None) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    base = f"v0:{ts}:{body.decode()}".encode()
    sig = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}


def test_verify_valid():
    p = SlackProvider(signing_secret=SECRET, client_id="c", client_secret="s")
    body = b'{"type":"event_callback"}'
    assert p.verify_webhook(_headers(body), body) is True


def test_verify_rejects_stale_timestamp():
    p = SlackProvider(signing_secret=SECRET, client_id="c", client_secret="s")
    body = b'{"type":"event_callback"}'
    old = str(int(time.time()) - 600)  # 10 min old
    assert p.verify_webhook(_headers(body, ts=old), body) is False


def test_normalize_app_mention():
    p = SlackProvider(signing_secret=SECRET, client_id="c", client_secret="s")
    payload = {
        "type": "event_callback",
        "event_id": "Ev1",
        "team_id": "T_SLACK",
        "event": {
            "type": "app_mention", "text": "<@U0> run tests",
            "channel": "C123", "ts": "1700.1", "thread_ts": "1700.0", "user": "U9",
        },
    }
    e = p.normalize_event(payload)
    assert e.event_type == "app_mention"
    assert e.resource == "C123"
    assert e.thread_key == "C123:1700.0"
    assert e.origin_ref == {"channel": "C123", "thread_ts": "1700.0"}
    assert e.external_id == "T_SLACK"


def test_normalize_app_mention_no_team_id_gives_none_external_id():
    """When team_id is absent external_id is None (safe: query matches nothing)."""
    p = SlackProvider(signing_secret=SECRET, client_id="c", client_secret="s")
    payload = {
        "type": "event_callback",
        "event_id": "Ev2",
        "event": {
            "type": "app_mention", "text": "hi",
            "channel": "C1", "ts": "1", "user": "U1",
        },
    }
    e = p.normalize_event(payload)
    assert e is not None
    assert e.external_id is None


@pytest.mark.asyncio
async def test_post_initial_returns_handle():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"ok": True, "channel": "C1", "ts": "100"}).encode(),
            headers={"content-type": "application/json"},
        )

    p = SlackProvider(signing_secret=SECRET, client_id="c", client_secret="s")
    p._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    handle = await p.post_initial(
        "tok", {"channel": "C1", "thread_ts": "99"}, "hello"
    )
    assert handle == {"channel": "C1", "ts": "100"}
