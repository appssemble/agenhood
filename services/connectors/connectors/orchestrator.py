from __future__ import annotations

import hashlib
import logging
from typing import Any

import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from connectors.connections_service import decrypt_cp_api_key
from connectors.deliveries_service import (
    build_delivery_row,
    find_open_delivery_for_thread,
)
from connectors.relay import run_relay
from connectors.routing import resolve_target
from connectors.tables import connections, deliveries, routing_rules, webhook_events
from connectors.webhook_dedupe import claim_delivery

log = logging.getLogger("connectors.orchestrator")


async def handle_event(
    *,
    provider: Any,
    payload: dict[str, Any],
    factory: async_sessionmaker[AsyncSession],
    cp_client: Any,
    master_key: bytes,
    coalesce_ms: int,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    ev = provider.normalize_event(payload)
    if ev is None:
        return {"status": "ignored"}

    async with factory() as session:
        digest = hashlib.sha256(repr(payload).encode()).hexdigest()
        if not await claim_delivery(session, ev.provider, ev.external_delivery_id, digest):
            await session.commit()
            return {"status": "duplicate"}
        await session.commit()

    # C1: filter connections to the originating workspace/installation only.
    # If ev.external_id is None the comparison becomes IS NULL; since external_id
    # is NOT NULL in the schema no rows match → safe no_route.
    async with factory() as session:
        conn_rows = (
            await session.execute(
                sa.select(connections).where(
                    connections.c.provider == ev.provider,
                    connections.c.status == "active",
                    connections.c.external_id == ev.external_id,
                )
            )
        ).mappings().all()
        for conn in conn_rows:
            rules = (
                await session.execute(
                    sa.select(routing_rules).where(
                        routing_rules.c.connection_id == conn["id"],
                        routing_rules.c.enabled.is_(True),
                    )
                )
            ).mappings().all()
            existing = await find_open_delivery_for_thread(
                session, connection_id=conn["id"], thread_key_origin=ev.origin_ref
            )
            target = resolve_target(
                ev, rules=[dict(r) for r in rules], existing_delivery=existing
            )
            if target is None:
                continue

            surface = (target.rule or {}).get("surface", ["reasoning", "result"])
            api_key = decrypt_cp_api_key(dict(conn), master_key)

            # I3: if submit_task raises, delete the dedupe claim so the provider
            # can retry this event successfully on its next attempt.
            try:
                task_id = await cp_client.submit_task(
                    container_id=target.container_id, api_key=api_key,
                    prompt=ev.text, metadata={"connector": ev.provider,
                                              "origin": ev.origin_ref},
                )
            except Exception:
                async with factory() as cleanup_session:
                    await cleanup_session.execute(
                        sa.delete(webhook_events).where(
                            webhook_events.c.provider == ev.provider,
                            webhook_events.c.external_delivery_id == ev.external_delivery_id,
                        )
                    )
                    await cleanup_session.commit()
                raise

            row = build_delivery_row(
                task_id=task_id, container_id=target.container_id,
                connection_id=conn["id"], origin_ref=ev.origin_ref, surface=surface,
            )
            await session.execute(sa.insert(deliveries).values(**row))
            await session.commit()

            token = await provider.mint_token(dict(conn), master_key)
            # C2: detach relay so the webhook response is not blocked.
            background_tasks.add_task(
                _relay_for_delivery,
                provider=provider, token=token, delivery=row,
                cp_client=cp_client, api_key=api_key, factory=factory,
                coalesce_ms=coalesce_ms,
            )
            return {"status": "triggered", "task_id": task_id}

    return {"status": "no_route"}


async def _relay_for_delivery(
    *,
    provider: Any,
    token: str,
    delivery: dict[str, Any],
    cp_client: Any,
    api_key: str,
    factory: async_sessionmaker[AsyncSession],
    coalesce_ms: int,
) -> None:
    async def save_progress(last_seq: int, state: str) -> None:
        async with factory() as s:
            await s.execute(
                sa.update(deliveries)
                .where(deliveries.c.id == delivery["id"])
                .values(last_seq=last_seq, state=state)
            )
            await s.commit()

    async def on_handle(h: dict[str, Any]) -> None:
        async with factory() as s:
            await s.execute(
                sa.update(deliveries)
                .where(deliveries.c.id == delivery["id"])
                .values(provider_message_handle=h)
            )
            await s.commit()

    events = cp_client.stream_events(
        container_id=delivery["container_id"], task_id=delivery["task_id"],
        api_key=api_key, after_seq=delivery["last_seq"],
    )
    try:
        await run_relay(
            events=events, provider=provider, token=token,
            origin_ref=delivery["origin_ref"], surface=delivery["surface"],
            coalesce_ms=coalesce_ms, save_progress=save_progress, on_handle=on_handle,
        )
    except Exception:  # noqa: BLE001 — a relay failure must not crash the webhook
        log.exception("relay failed for delivery %s", delivery["id"])
        await save_progress(delivery["last_seq"], "failed")
