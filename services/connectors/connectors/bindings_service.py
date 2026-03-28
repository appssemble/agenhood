from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from connectors.ids import new_id


def build_binding_row(
    *,
    connection_id: str,
    container_id: str,
    tenant_id: str,
    enabled: bool,
    resource_filters: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_id("bnd"),
        "connection_id": connection_id,
        "container_id": container_id,
        "tenant_id": tenant_id,
        "enabled": enabled,
        "resource_filters": resource_filters,
        "created_at": now,
        "updated_at": now,
    }
