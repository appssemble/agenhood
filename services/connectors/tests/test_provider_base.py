import pytest

from connectors.models import NormalizedEvent

pytestmark = pytest.mark.unit


def test_normalized_event_fields():
    e = NormalizedEvent(
        provider="github", event_type="issue_comment", external_delivery_id="d1",
        resource="org/api", thread_key="org/api#42", text="/agent web run tests",
        origin_ref={"repo": "org/api", "number": 42, "comment_id": 7},
        actor="octocat",
    )
    assert e.thread_key == "org/api#42"
    assert e.origin_ref["number"] == 42
