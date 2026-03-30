from __future__ import annotations

import asyncio
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from connectors.connections_service import decrypt_cp_api_key
from connectors.tables import connections, deliveries

log = logging.getLogger("connectors.resume")


async def resume_open_deliveries(
    *,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    providers: dict[str, Any],
    cp_client: Any,
    master_key: bytes,
    coalesce_ms: int,
) -> None:
    async with factory() as session:
        rows = (
            await session.execute(
                sa.select(deliveries).where(deliveries.c.state == "streaming")
            )
        ).mappings().all()
        open_deliveries = [dict(r) for r in rows]
        conn_rows = (
            await session.execute(sa.select(connections))
        ).mappings().all()
        conn_by_id = {c["id"]: dict(c) for c in conn_rows}

    # I4: run all resumed relays concurrently so one slow/failing delivery
    # does not block the others; each task has its own try/except.
    tasks = []
    for delivery in open_deliveries:
        conn = conn_by_id.get(delivery["connection_id"])
        if conn is None:
            continue
        provider = providers.get(conn["provider"])
        if provider is None:
            continue
        api_key = decrypt_cp_api_key(conn, master_key)
        token = await provider.mint_token(conn, master_key)
        tasks.append(
            asyncio.create_task(
                _relay_for_delivery_resumed(
                    provider=provider, token=token, delivery=delivery,
                    cp_client=cp_client, api_key=api_key, factory=factory,
                    coalesce_ms=coalesce_ms,
                )
            )
        )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _relay_for_delivery_resumed(
    *, provider: Any, token: str, delivery: dict[str, Any],
    cp_client: Any, api_key: str, factory: async_sessionmaker,  # type: ignore[type-arg]
    coalesce_ms: int,
) -> None:
    from connectors.relay import run_relay

    async def save_progress(last_seq: int, state: str) -> None:
        async with factory() as s:
            await s.execute(
                sa.update(deliveries).where(deliveries.c.id == delivery["id"])
                .values(last_seq=last_seq, state=state)
            )
            await s.commit()

    events = cp_client.stream_events(
        container_id=delivery["container_id"], task_id=delivery["task_id"],
        api_key=api_key, after_seq=delivery["last_seq"],
    )
    # I4: isolate per-delivery failures so one bad delivery doesn't abort others.
    try:
        await run_relay(
            events=events, provider=provider, token=token,
            origin_ref=delivery["origin_ref"], surface=delivery["surface"],
            coalesce_ms=coalesce_ms, save_progress=save_progress,
            handle=delivery.get("provider_message_handle"),
        )
    except Exception:  # noqa: BLE001
        log.exception("resumed relay failed for delivery %s", delivery["id"])
        await save_progress(delivery["last_seq"], "failed")
