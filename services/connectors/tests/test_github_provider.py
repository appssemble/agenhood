import hashlib
import hmac

import pytest

from connectors.providers.github import GitHubProvider

pytestmark = pytest.mark.unit

SECRET = "whsec_test"


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_valid_signature():
    p = GitHubProvider(app_id="1", private_key_pem="x", webhook_secret=SECRET)
    body = b'{"action":"created"}'
    assert p.verify_webhook({"X-Hub-Signature-256": _sig(body)}, body) is True


def test_verify_rejects_tampered():
    p = GitHubProvider(app_id="1", private_key_pem="x", webhook_secret=SECRET)
    body = b'{"action":"created"}'
    assert p.verify_webhook({"X-Hub-Signature-256": _sig(b"other")}, body) is False


def test_normalize_issue_comment():
    p = GitHubProvider(app_id="1", private_key_pem="x", webhook_secret=SECRET)
    payload = {
        "action": "created",
        "repository": {"full_name": "org/api"},
        "issue": {"number": 42},
        "comment": {"id": 7, "body": "/agent run tests"},
        "sender": {"login": "octocat"},
        "installation": {"id": 12345},
        "_github_event": "issue_comment",
        "_delivery_id": "d-123",
    }
    e = p.normalize_event(payload)
    assert e is not None
    assert e.event_type == "issue_comment"
    assert e.resource == "org/api"
    assert e.thread_key == "org/api#42"
    assert e.origin_ref == {"repo": "org/api", "number": 42, "comment_id": 7}
    assert e.text == "/agent run tests"
    assert e.external_id == "12345"


def test_normalize_issue_comment_no_installation_gives_none_external_id():
    """When installation is absent external_id is None (safe: query matches nothing)."""
    p = GitHubProvider(app_id="1", private_key_pem="x", webhook_secret=SECRET)
    payload = {
        "action": "created",
        "repository": {"full_name": "org/api"},
        "issue": {"number": 1},
        "comment": {"id": 1, "body": "hi"},
        "sender": {"login": "octocat"},
        "_github_event": "issue_comment",
        "_delivery_id": "d-999",
    }
    e = p.normalize_event(payload)
    assert e is not None
    assert e.external_id is None
