from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Trigger self-registration of all built-in drivers and tools.
import agentcore.drivers.vanilla  # noqa: F401
import agentcore.tools  # noqa: F401
from agentcore.drivers.base import DRIVERS
from control_plane.auth.passwords import hash_password
from control_plane.auth.tokens import API_KEY_PREFIX_LEN
from control_plane.config import Settings
from control_plane.db import make_engine, make_session_factory
from control_plane.ids import new_template_id
from control_plane.ids_compat import new_id
from control_plane.models_db import templates, tenants
from control_plane.tables import api_keys, users

# Defaults mirror spec §4.4. Anthropic-only models in v1.
SEED_TENANT_LIMITS: dict[str, Any] = {
    "max_containers": 2000,
    "max_running_containers": 30,
    "max_users": 25,
    "max_concurrent_tasks_per_container": 4,
    "max_workspace_volume_size_mb": 10240,
    "default_task_timeout_seconds": 1800,
    "default_max_iterations": 30,
    "default_max_tokens": 2000000,
    "idle_pause_minutes": 20,
    "archive_after_hours": 72,
    "reclaim_after_days": 30,
    # allowed_drivers is intentionally NOT frozen here: it is resolved from the
    # current defaults at read time (see tenant_defaults.persisted_limits /
    # merge_limits) so the seed tenant always tracks the installed driver set.
}


def build_builtin_template_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, driver in DRIVERS.items():
        dt = driver.default_template
        rows.append(
            {
                "id": new_template_id(),
                "tenant_id": None,
                "name": f"{name} (built-in default)",
                "driver": name,
                "model": None,
                "system_prompt": dt.default_system_prompt,
                "system_prompt_mode": "augment",
                "tools": list(dt.available_tools),
                "context": {},
                "skills": [],
                "limits": {},
                "is_builtin": True,
                "created_by": None,
            }
        )
    return rows


async def apply_seed(session: AsyncSession, settings: Settings) -> None:
    # Seed tenant (idempotent).
    existing_tenant = (
        await session.execute(select(tenants.c.id).where(tenants.c.id == settings.seed_tenant_id))
    ).scalar_one_or_none()
    if existing_tenant is None:
        await session.execute(
            tenants.insert().values(
                id=settings.seed_tenant_id,
                name="Seed Tenant",
                limits=SEED_TENANT_LIMITS,
                status="active",
            )
        )

    # Seed API key for the seed tenant (idempotent: only if seed_api_key is configured).
    # The seed key's prefix is the first API_KEY_PREFIX_LEN chars of the full secret.
    seed_key = settings.seed_api_key
    if seed_key:
        seed_prefix = seed_key[:API_KEY_PREFIX_LEN]
        existing_key = (
            await session.execute(
                select(api_keys.c.id).where(
                    api_keys.c.key_prefix == seed_prefix,
                    api_keys.c.tenant_id == settings.seed_tenant_id,
                )
            )
        ).scalar_one_or_none()
        if existing_key is None:
            await session.execute(
                api_keys.insert().values(
                    id=new_id("key"),
                    tenant_id=settings.seed_tenant_id,
                    name="Seed API Key",
                    key_hash=hash_password(seed_key),
                    key_prefix=seed_prefix,
                    created_by=None,
                    last_used_at=None,
                    status="active",
                    revoked_at=None,
                    created_at=datetime.now(UTC),
                )
            )

    # Seed staff (admin) login (idempotent: skip if the email already exists).
    # The intended first-login path instead of bootstrapping via ADMIN_API_KEY.
    # must_change_password rotates the env-provided bootstrap password on first login.
    staff_email = settings.seed_staff_email.strip().lower()
    if staff_email and settings.seed_staff_password:
        existing_user = (
            await session.execute(select(users.c.id).where(users.c.email == staff_email))
        ).scalar_one_or_none()
        if existing_user is None:
            now = datetime.now(UTC)
            await session.execute(
                users.insert().values(
                    id=new_id("usr"),
                    email=staff_email,
                    name=settings.seed_staff_name,
                    password_hash=hash_password(settings.seed_staff_password),
                    is_staff=True,
                    must_change_password=True,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )

    # Built-in templates — one per driver, skip drivers already seeded.
    seeded_drivers = set(
        (await session.execute(
            select(templates.c.driver).where(templates.c.is_builtin.is_(True))
        )).scalars().all()
    )
    for row in build_builtin_template_rows():
        if row["driver"] in seeded_drivers:
            continue
        await session.execute(templates.insert().values(**row))

    await session.commit()


async def _amain() -> None:
    settings = Settings.from_env()
    engine = make_engine(settings)
    try:
        factory = make_session_factory(engine)
        async with factory() as session:
            await apply_seed(session, settings)
    finally:
        await engine.dispose()


def main() -> None:
    """CLI entry: `python -m control_plane.seed` — idempotently seeds the DB."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
