"""align metadata/settings columns with the JSONB contract declared by the models

Migration 0001 created these columns with sa.JSON() (renders as `json`), while
backend/db/models.py declares JSONB. Align them to jsonb.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (
        ("index_versions", "chunk_settings"),
        ("index_versions", "source_manifest"),
        ("parent_chunks", "metadata"),
        ("child_chunks", "metadata"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE jsonb USING {column}::jsonb"
        )


def downgrade() -> None:
    for table, column in (
        ("index_versions", "chunk_settings"),
        ("index_versions", "source_manifest"),
        ("parent_chunks", "metadata"),
        ("child_chunks", "metadata"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE json USING {column}::json"
        )
