"""workspace git rollback: git_remotes table

Revision ID: 0006_git_remotes
Revises: 0005_chatgpt_subscription_auth
Create Date: 2026-06-12
"""
from __future__ import annotations

from alembic import op

revision = "0006_git_remotes"
down_revision = "0005_chatgpt_subscription_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE git_remotes (
            container_id     TEXT PRIMARY KEY
                             REFERENCES containers(id) ON DELETE CASCADE,
            url              TEXT NOT NULL,
            branch           TEXT NOT NULL DEFAULT 'main',
            token_ciphertext BYTEA,
            token_last4      TEXT,
            enabled          BOOLEAN NOT NULL DEFAULT TRUE,
            last_push_status TEXT,
            last_push_error  TEXT,
            last_push_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS git_remotes")
