from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connectors.models import NormalizedEvent


@dataclass(frozen=True)
class ResolvedTarget:
    container_id: str
    rule: dict[str, Any] | None
    reason: str  # "thread" | "rule"


def _match_channel(match: dict[str, Any], ev: NormalizedEvent) -> bool:
    want = match.get("channel") or match.get("repo")
    return want is None or want == ev.resource


def _match_slug(match: dict[str, Any], ev: NormalizedEvent) -> bool:
    slug = match.get("slug")
    if not slug:
        return True
    # token-match: the slug must appear as a whitespace-delimited word in the text.
    return slug in ev.text.split()


def _match_event(match: dict[str, Any], ev: NormalizedEvent) -> bool:
    want = match.get("event")
    return want is None or want == ev.event_type


def resolve_target(
    ev: NormalizedEvent,
    *,
    rules: list[dict[str, Any]],
    existing_delivery: dict[str, Any] | None,
) -> ResolvedTarget | None:
    # 1. Thread / conversation continuity wins.
    if existing_delivery:
        return ResolvedTarget(
            container_id=existing_delivery["container_id"], rule=None, reason="thread"
        )
    # 2-4. Evaluate rules by ascending priority; first full match wins.
    for rule in sorted(rules, key=lambda r: r.get("priority", 100)):
        m = rule.get("match", {})
        if _match_event(m, ev) and _match_channel(m, ev) and _match_slug(m, ev):
            cid = rule.get("target", {}).get("container_id")
            if cid:
                return ResolvedTarget(container_id=cid, rule=rule, reason="rule")
    return None
