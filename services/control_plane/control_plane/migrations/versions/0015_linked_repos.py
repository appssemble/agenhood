"""linked repos (pull mode): linked_repos table + containers.git_mode

Revision ID: 0015_linked_repos
Revises: 0014_drop_owner_once
Create Date: 2026-06-22
"""
from __future__ import annotations

from alembic import op

revision = "0015_linked_repos"
down_revision = "0014_drop_owner_once"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE containers "
        "ADD COLUMN git_mode TEXT NOT NULL DEFAULT 'snapshot'"
    )
    op.execute(
        """
        CREATE TABLE linked_repos (
            container_id                TEXT PRIMARY KEY
                                        REFERENCES containers(id) ON DELETE CASCADE,
            url                         TEXT NOT NULL DEFAULT '',
            branch                      TEXT NOT NULL DEFAULT 'main',
            ssh_private_key_ciphertext  BYTEA,
            ssh_public_key              TEXT,
            key_type                    TEXT,
            key_fingerprint             TEXT,
            verified_at                 TIMESTAMPTZ,
            linked_at                   TIMESTAMPTZ,
            last_clone_status           TEXT,
            last_clone_error            TEXT,
            last_clone_at               TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS linked_repos")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS git_mode")
