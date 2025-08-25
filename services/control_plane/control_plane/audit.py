from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert

from control_plane.models_db import audit_log

log = logging.getLogger("control_plane.audit")


async def audit(
    session: Any,
    *,
    actor_type: str,                 # tenant | admin | system
    action: str,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one row to audit_log. Never raises into the caller's path:
    a failed audit write is logged but must not abort the action being audited."""
    try:
        await session.execute(
            insert(audit_log).values(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
        )
    except Exception:  # pragma: no cover - exercised by test_audit_failure_is_swallowed
        log.exception("audit write failed", extra={"action": action, "target_id": target_id})
