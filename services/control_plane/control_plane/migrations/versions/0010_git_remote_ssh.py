"""link-a-remote: swap HTTPS token for SSH deploy keypair

Revision ID: 0010_git_remote_ssh
Revises: 0009_skill_sources
Create Date: 2026-06-16
"""
from __future__ import annotations

from alembic import op

revision = "0010_git_remote_ssh"
down_revision = "0009_skill_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE git_remotes
            DROP COLUMN IF EXISTS token_ciphertext,
            DROP COLUMN IF EXISTS token_last4,
            ADD COLUMN ssh_private_key_ciphertext BYTEA,
            ADD COLUMN ssh_public_key             TEXT,
            ADD COLUMN key_type                   TEXT,
            ADD COLUMN key_fingerprint            TEXT,
            ADD COLUMN verified_at                TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE git_remotes
            DROP COLUMN IF EXISTS ssh_private_key_ciphertext,
            DROP COLUMN IF EXISTS ssh_public_key,
            DROP COLUMN IF EXISTS key_type,
            DROP COLUMN IF EXISTS key_fingerprint,
            DROP COLUMN IF EXISTS verified_at,
            ADD COLUMN token_ciphertext BYTEA,
            ADD COLUMN token_last4      TEXT
        """
    )
