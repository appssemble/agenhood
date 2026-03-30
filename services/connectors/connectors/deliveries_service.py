from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.ids import new_id
from connectors.tables import deliveries


def build_delivery_row(
    *,
    task_id: str,
    container_id: str,
    connection_id: str,
    origin_ref: dict[str, Any],
    surface: list[str],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_id("dlv"),
        "task_id": task_id,
        "container_id": container_id,
        "connection_id": connection_id,
        "origin_ref": origin_ref,
        "provider_message_handle": None,
        "surface": surface,
        "last_seq": 0,
        "state": "streaming",
        "created_at": now,
        "updated_at": now,
    }


async def find_open_delivery_for_thread(
    session: AsyncSession, *, connection_id: str, thread_key_origin: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the most recent delivery whose origin matches this thread, else None.

    This drives thread-continuity routing (spec §6 rule 1): a follow-up in a
    thread routes to the container that started it. Continuity intentionally
    spans *completed* deliveries too — a back-and-forth stays with the same
    agent even after its first task finished — so this does NOT filter on
    ``state``. Rows are ordered most-recent-first so the result is deterministic
    when a thread has several deliveries (all share the same container_id).

    Matches on the JSON origin_ref fields that define a thread:
    Slack (channel, thread_ts) or GitHub (repo, number).
    """
    rows = (
        await session.execute(
            sa.select(deliveries)
            .where(deliveries.c.connection_id == connection_id)
            .order_by(deliveries.c.created_at.desc())
        )
    ).mappings().all()
    for r in rows:
        ref = r["origin_ref"]
        if _same_thread(ref, thread_key_origin):
            return dict(r)
    return None


def _same_thread(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if "channel" in a and "channel" in b:
        return a.get("channel") == b.get("channel") and a.get("thread_ts") == b.get("thread_ts")
    if "repo" in a and "repo" in b:
        return a.get("repo") == b.get("repo") and a.get("number") == b.get("number")
    return False
