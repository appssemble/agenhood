"""codex tools: empty tool lists become ["web_search"]

Codex now reads ``tools`` (listed = on). Before, it ignored the list and
always had web search on, so empty codex lists are backfilled to keep that.

Revision ID: 0029_codex_default_tools
Revises: 0028_env_vars
Create Date: 2026-09-26
"""
from __future__ import annotations

from alembic import op

revision = "0029_codex_default_tools"
down_revision = "0028_env_vars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE templates SET tools = '[\"web_search\"]'::jsonb "
        "WHERE driver = 'codex' AND tools = '[]'::jsonb"
    )
    op.execute(
        "UPDATE containers "
        "SET config = jsonb_set(config, '{tools}', '[\"web_search\"]'::jsonb) "
        "WHERE config->>'driver' = 'codex' "
        "AND COALESCE(config->'tools', '[]'::jsonb) = '[]'::jsonb"
    )


def downgrade() -> None:
    # Older code rejects any non-empty codex tool list; [] means web search on.
    op.execute("UPDATE templates SET tools = '[]'::jsonb WHERE driver = 'codex'")
    op.execute(
        "UPDATE containers SET config = jsonb_set(config, '{tools}', '[]'::jsonb) "
        "WHERE config->>'driver' = 'codex'"
    )
