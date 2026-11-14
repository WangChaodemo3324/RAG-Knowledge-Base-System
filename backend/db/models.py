from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024

VERSION_STATUS_BUILDING = "building"
VERSION_STATUS_ACTIVE = "active"
VERSION_STATUS_RETIRED = "retired"
VERSION_STATUS_FAILED = "failed"

TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_FAILED = "failed"


class Base(DeclarativeBase):
    pass


class IndexVersion(Base):
    """A full snapshot of the index. Reads only ever target the active version."""

    __tablename__ = "index_versions"
    __table_args__ = (
        Index(
            "ux_index_versions_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=VERSION_STATUS_BUILDING, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dim: Mapped[int] = mapped_column(Integer, default=EMBEDDING_DIM)
    metadata_schema_version: Mapped[str] = mapped_column(String(40), default="")
    chunk_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentRecord(Base):
    """Per-file record inside one index version (replaces manifest.json records)."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("version_id", "file_name", name="ux_documents_version_file"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("index_versions.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    modified_at: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="indexed")
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParentChunk(Base):
    __tablename__ = "parent_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "parent_id", name="ux_parent_chunks_version_parent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("index_versions.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str] = mapped_column(String(80))
    parent_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class ChildChunk(Base):
    """Embedded child chunk; the only table carrying vectors."""

    __tablename__ = "child_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "child_id", name="ux_child_chunks_version_child"),
        Index(
            "ix_child_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("index_versions.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parent_pk: Mapped[int] = mapped_column(ForeignKey("parent_chunks.id", ondelete="CASCADE"), index=True)
    child_id: Mapped[str] = mapped_column(String(80))
    child_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class IndexTask(Base):
    """State machine for indexing jobs, used for concurrency control and recovery."""

    __tablename__ = "index_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=TASK_RUNNING, index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("index_versions.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
