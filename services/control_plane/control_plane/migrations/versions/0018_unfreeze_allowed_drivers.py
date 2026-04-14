"""unfreeze allowed_drivers: let non-restricted tenants track the default driver set

Historically a tenant's full limits block (including ``allowed_drivers``) was
frozen into the row at creation time, so adding a driver to the platform defaults
never reached existing tenants — they kept the stale list and rejected the new
driver. Going forward ``allowed_drivers`` is resolved from current defaults at
read time (tenant_defaults.persisted_limits / merge_limits) and only persisted
when an admin explicitly restricts a tenant.

This migration removes the ``allowed_drivers`` key from existing rows whose stored
value is a *known default snapshot* (i.e. not a deliberate restriction). Matching
on exact known-default sets preserves any genuinely custom allowlist while letting
the common stale rows fall through to the current default set.

Revision ID: 0018_unfreeze_allowed_drivers
Revises: 0017_prompts
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op

revision = "0018_unfreeze_allowed_drivers"
down_revision = "0017_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Strip allowed_drivers only where the stored (order-insensitive) set equals a
    # recognized historical default — these were frozen by the old write path, not
    # chosen as a per-tenant restriction. A genuinely custom set is left intact.
    op.execute(
        """
        UPDATE tenants
        SET limits = limits - 'allowed_drivers'
        WHERE limits ? 'allowed_drivers'
          AND (
            SELECT array_agg(d ORDER BY d)
            FROM jsonb_array_elements_text(limits->'allowed_drivers') AS d
          ) IN (
            ARRAY['codex', 'opencode', 'vanilla'],
            ARRAY['claude-code', 'codex', 'opencode', 'vanilla']
          )
        """
    )


def downgrade() -> None:
    # Best-effort: re-freeze the current default driver set onto any row missing
    # the key. (The original per-tenant value is not recoverable.)
    op.execute(
        """
        UPDATE tenants
        SET limits = jsonb_set(
            limits,
            '{allowed_drivers}',
            '["vanilla", "opencode", "codex", "claude-code"]'::jsonb
        )
        WHERE NOT (limits ? 'allowed_drivers')
        """
    )
