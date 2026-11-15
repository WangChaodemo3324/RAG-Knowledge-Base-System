"""initial schema: index versions, documents, parent/child chunks, index tasks

Revision ID: 0001
Revises:
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from backend.db.models import EMBEDDING_DIM

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "index_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="building"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default=str(EMBEDDING_DIM)),
        sa.Column("metadata_schema_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("chunk_settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_manifest", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_index_versions_status", "index_versions", ["status"])
    op.create_index(
        "ux_index_versions_one_active",
        "index_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("modified_at", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="indexed"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("version_id", "file_name", name="ux_documents_version_file"),
    )
    op.create_index("ix_documents_version_id", "documents", ["version_id"])

    op.create_table(
        "parent_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.String(length=80), nullable=False),
        sa.Column("parent_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("version_id", "parent_id", name="ux_parent_chunks_version_parent"),
    )
    op.create_index("ix_parent_chunks_version_id", "parent_chunks", ["version_id"])
    op.create_index("ix_parent_chunks_document_id", "parent_chunks", ["document_id"])

    op.create_table(
        "child_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_pk", sa.BigInteger(), sa.ForeignKey("parent_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("child_id", sa.String(length=80), nullable=False),
        sa.Column("child_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("version_id", "child_id", name="ux_child_chunks_version_child"),
    )
    op.create_index("ix_child_chunks_version_id", "child_chunks", ["version_id"])
    op.create_index("ix_child_chunks_document_id", "child_chunks", ["document_id"])
    op.create_index("ix_child_chunks_parent_pk", "child_chunks", ["parent_pk"])
    op.create_index(
        "ix_child_chunks_embedding_hnsw",
        "child_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "index_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("index_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_index_tasks_status", "index_tasks", ["status"])


def downgrade() -> None:
    op.drop_table("index_tasks")
    op.drop_index("ix_child_chunks_embedding_hnsw", table_name="child_chunks")
    op.drop_table("child_chunks")
    op.drop_table("parent_chunks")
    op.drop_table("documents")
    op.drop_index("ux_index_versions_one_active", table_name="index_versions")
    op.drop_index("ix_index_versions_status", table_name="index_versions")
    op.drop_table("index_versions")
