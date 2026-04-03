import pytest

from connectors.models import NormalizedEvent
from connectors.routing import ResolvedTarget, resolve_target

pytestmark = pytest.mark.unit


def _ev(text="hi", thread_key="C1:100", resource="C1"):
    return NormalizedEvent(
        provider="slack", event_type="app_mention", external_delivery_id="d",
        resource=resource, thread_key=thread_key, text=text,
        origin_ref={"channel": "C1", "thread_ts": "100"},
    )


def test_thread_continuity_wins(_=None):
    existing = {"container_id": "cnt_prev"}
    rules = [{"priority": 1, "match": {"channel": "C1"}, "target": {"container_id": "cnt_rule"}}]
    r = resolve_target(_ev(), rules=rules, existing_delivery=existing)
    assert r == ResolvedTarget(container_id="cnt_prev", rule=None, reason="thread")


def test_resource_match():
    rules = [{"priority": 10, "match": {"channel": "C1"}, "target": {"container_id": "cnt_a"},
              "surface": ["reasoning"], "input_template": "{{ text }}"}]
    r = resolve_target(_ev(), rules=rules, existing_delivery=None)
    assert r.container_id == "cnt_a"
    assert r.reason == "rule"


def test_explicit_slug_selects_among_same_channel():
    rules = [
        {"priority": 10, "match": {"channel": "C1", "slug": "web"},
         "target": {"container_id": "cnt_web"}},
        {"priority": 10, "match": {"channel": "C1", "slug": "api"},
         "target": {"container_id": "cnt_api"}},
    ]
    r = resolve_target(_ev(text="<@U0> api deploy"), rules=rules, existing_delivery=None)
    assert r.container_id == "cnt_api"


def test_ordered_first_match_when_ambiguous():
    rules = [
        {"priority": 5, "match": {"channel": "C1"}, "target": {"container_id": "cnt_first"}},
        {"priority": 9, "match": {"channel": "C1"}, "target": {"container_id": "cnt_second"}},
    ]
    r = resolve_target(_ev(), rules=rules, existing_delivery=None)
    assert r.container_id == "cnt_first"


def test_no_match_returns_none():
    rules = [{"priority": 5, "match": {"channel": "C-other"}, "target": {"container_id": "x"}}]
    assert resolve_target(_ev(), rules=rules, existing_delivery=None) is None
