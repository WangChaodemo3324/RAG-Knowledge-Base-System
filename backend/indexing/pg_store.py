"""PostgreSQL + pgvector storage adapter.

Replaces Chroma (vector index) and the JSON stores (parents/children/manifest)
with one versioned, transactional source of truth:

- every read targets the single ACTIVE index version;
- builds write into a `building` version and switch atomically (blue-green);
- per-document updates swap chunks inside one transaction (no delete-first);
- retrieval shapes stay compatible with the existing service contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.db.models import (
    ChildChunk,
    DocumentRecord,
    EMBEDDING_DIM,
    IndexTask,
    IndexVersion,
    ParentChunk,
    TASK_FAILED,
    TASK_RUNNING,
    TASK_SUCCEEDED,
    VERSION_STATUS_ACTIVE,
    VERSION_STATUS_BUILDING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_RETIRED,
)


class VersionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Version lifecycle
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_active_version(session: Session) -> IndexVersion | None:
    return session.execute(
        select(IndexVersion).where(IndexVersion.is_active.is_(True))
    ).scalar_one_or_none()


def require_active_version(session: Session) -> IndexVersion:
    version = get_active_version(session)
    if version is None:
        raise VersionError("No active index version. Build and activate one first.")
    return version


def create_building_version(
    session: Session,
    name: str,
    embedding_model: str,
    chunk_settings: dict[str, Any],
    metadata_schema_version: str,
    notes: str = "",
) -> IndexVersion:
    exists = session.execute(select(IndexVersion).where(IndexVersion.name == name)).scalar_one_or_none()
    if exists is not None:
        raise VersionError(f"Index version name already exists: {name}")
    version = IndexVersion(
        name=name,
        status=VERSION_STATUS_BUILDING,
        is_active=False,
        embedding_model=embedding_model,
        embedding_dim=EMBEDDING_DIM,
        metadata_schema_version=metadata_schema_version,
        chunk_settings=chunk_settings,
        notes=notes,
    )
    session.add(version)
    session.flush()
    return version


def activate_version(session: Session, version_id: int) -> IndexVersion:
    version = session.get(IndexVersion, version_id)
    if version is None:
        raise VersionError(f"Index version not found: {version_id}")
    if version.status not in (VERSION_STATUS_BUILDING, VERSION_STATUS_RETIRED):
        raise VersionError(f"Cannot activate version in status={version.status}")
    current = get_active_version(session)
    if current is not None and current.id == version.id:
        return version
    if current is not None:
        current.is_active = False
        current.status = VERSION_STATUS_RETIRED
        current.retired_at = datetime.now(timezone.utc)
    version.is_active = True
    version.status = VERSION_STATUS_ACTIVE
    version.activated_at = datetime.now(timezone.utc)
    session.flush()
    return version


def mark_version_failed(session: Session, version_id: int, error: str) -> None:
    version = session.get(IndexVersion, version_id)
    if version is None or version.is_active:
        return
    version.status = VERSION_STATUS_FAILED
    version.notes = f"{version.notes}\nfailed: {error}".strip()
    session.flush()


def list_versions(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(IndexVersion).order_by(IndexVersion.id.desc())
    ).scalars().all()
    return [
        {
            "id": version.id,
            "name": version.name,
            "status": version.status,
            "is_active": version.is_active,
            "embedding_model": version.embedding_model,
            "created_at": version.created_at.isoformat() if version.created_at else "",
            "activated_at": version.activated_at.isoformat() if version.activated_at else "",
        }
        for version in rows
    ]


# ---------------------------------------------------------------------------
# Tasks (concurrency + recovery)
# ---------------------------------------------------------------------------


def start_task(session: Session, task_type: str, version_id: int | None = None) -> IndexTask:
    # Transaction-scoped advisory lock closes the check-then-insert race between
    # concurrent workers; the committed `running` task row guards afterwards.
    locked = session.execute(select(func.pg_try_advisory_xact_lock(987654321))).scalar()
    if not locked:
        raise VersionError("Another indexing task holds the advisory lock")
    running = session.execute(
        select(IndexTask).where(IndexTask.status == TASK_RUNNING)
    ).scalars().all()
    if running:
        raise VersionError(
            f"Another indexing task is running (id={running[0].id}, type={running[0].task_type})"
        )
    task = IndexTask(task_type=task_type, status=TASK_RUNNING, version_id=version_id)
    session.add(task)
    session.flush()
    return task


def finish_task(session: Session, task_id: int, succeeded: bool, message: str = "", error: str = "") -> None:
    task = session.get(IndexTask, task_id)
    if task is None:
        return
    task.status = TASK_SUCCEEDED if succeeded else TASK_FAILED
    task.message = message
    task.error = error
    task.updated_at = datetime.now(timezone.utc)
    session.flush()


def recover_stale_tasks(session: Session, stale_version_ids: Iterable[int]) -> int:
    """Fail running tasks left behind by a crashed process; fail their building versions."""
    running = session.execute(
        select(IndexTask).where(IndexTask.status == TASK_RUNNING)
    ).scalars().all()
    recovered = 0
    for task in running:
        task.status = TASK_FAILED
        task.error = f"recovered: process restarted while task was running ({now_iso()})"
        recovered += 1
        if task.version_id is not None:
            mark_version_failed(session, task.version_id, "process restarted during build")
    for version_id in stale_version_ids:
        mark_version_failed(session, version_id, "stale building version on startup")
    return recovered


# ---------------------------------------------------------------------------
# Document / chunk writes
# ---------------------------------------------------------------------------


def new_chunk_id() -> str:
    return uuid.uuid4().hex


def upsert_document(
    session: Session,
    version_id: int,
    file_name: str,
    file_hash: str,
    file_size: int,
    modified_at: str,
    document_count: int,
    status: str = "indexed",
    error: str = "",
) -> DocumentRecord:
    record = session.execute(
        select(DocumentRecord).where(
            DocumentRecord.version_id == version_id,
            DocumentRecord.file_name == file_name,
        )
    ).scalar_one_or_none()
    if record is None:
        record = DocumentRecord(version_id=version_id, file_name=file_name)
        session.add(record)
    record.file_hash = file_hash
    record.file_size = file_size
    record.modified_at = modified_at
    record.status = status
    record.document_count = document_count
    record.error = error
    record.indexed_at = datetime.now(timezone.utc)
    # stale counts are overwritten by the caller once chunks are written
    record.parent_count = 0
    record.chunk_count = 0
    session.flush()
    return record


def write_chunks(
    session: Session,
    version_id: int,
    record: DocumentRecord,
    parents: Sequence[dict[str, Any]],
    children: Sequence[dict[str, Any]],
) -> None:
    """Insert parents + children for one document, updating record counts.

    Callers must delete this document's previous chunks in the SAME transaction
    before invoking this (swap-in-place) — see delete_document_chunks.
    """
    parent_pk_by_index: dict[int, int] = {}
    for parent in parents:
        row = ParentChunk(
            version_id=version_id,
            document_id=record.id,
            parent_id=parent["parent_id"],
            parent_index=parent.get("parent_index", 0),
            content=parent["content"],
            chunk_metadata=dict(parent.get("metadata") or {}),
        )
        session.add(row)
        session.flush()
        parent_pk_by_index[parent.get("parent_index", 0)] = row.id

    for child in children:
        session.add(
            ChildChunk(
                version_id=version_id,
                document_id=record.id,
                parent_pk=parent_pk_by_index[child.get("parent_index", 0)],
                child_id=child["child_id"],
                child_index=child.get("child_index", 0),
                content=child["content"],
                embedding=child["embedding"],
                chunk_metadata=dict(child.get("metadata") or {}),
            )
        )

    record.parent_count = len(parents)
    record.chunk_count = len(children)
    session.flush()


def delete_document_chunks(session: Session, record: DocumentRecord) -> None:
    session.execute(delete(ChildChunk).where(ChildChunk.document_id == record.id))
    session.execute(delete(ParentChunk).where(ParentChunk.document_id == record.id))
    session.flush()


def get_document(session: Session, version_id: int, file_name: str) -> DocumentRecord | None:
    return session.execute(
        select(DocumentRecord).where(
            DocumentRecord.version_id == version_id,
            DocumentRecord.file_name == file_name,
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Reads (always version-scoped)
# ---------------------------------------------------------------------------


def search_children(
    session: Session,
    version_id: int,
    query_embedding: Sequence[float],
    top_k: int,
    file_name: str = "",
) -> list[dict[str, Any]]:
    stmt = (
        select(ChildChunk, ParentChunk.parent_id, DocumentRecord.file_name)
        .join(ParentChunk, ChildChunk.parent_pk == ParentChunk.id)
        .join(DocumentRecord, ChildChunk.document_id == DocumentRecord.id)
        .where(ChildChunk.version_id == version_id)
        .order_by(ChildChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    if file_name:
        stmt = stmt.where(DocumentRecord.file_name == file_name)

    rows = session.execute(stmt).all()
    return [
        {
            "retrieval_level": "child",
            "child_id": child.child_id,
            "parent_id": parent_id,
            "file_name": file,
            "source": file,
            "content": child.content,
            "preview": child.content[:220],
            "metadata": dict(child.chunk_metadata or {}),
        }
        for child, parent_id, file in rows
    ]


def load_children_for_bm25(session: Session, version_id: int) -> list[dict[str, Any]]:
    stmt = (
        select(ChildChunk, ParentChunk.parent_id, DocumentRecord.file_name)
        .join(ParentChunk, ChildChunk.parent_pk == ParentChunk.id)
        .join(DocumentRecord, ChildChunk.document_id == DocumentRecord.id)
        .where(ChildChunk.version_id == version_id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "child_id": child.child_id,
            "parent_id": parent_id,
            "file_name": file,
            "content": child.content,
            "metadata": dict(child.chunk_metadata or {}),
        }
        for child, parent_id, file in rows
    ]


def expand_children_to_parents(
    session: Session,
    version_id: int,
    child_records: Sequence[dict[str, Any]],
    top_k: int,
    extra_child_fields: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Parent expansion with parent dedup, mirroring the previous ParentStore behavior."""
    expanded: list[dict[str, Any]] = []
    seen_parent_ids: set[str] = set()
    for record in child_records:
        parent_id = str(record.get("parent_id") or "")
        if parent_id and parent_id in seen_parent_ids:
            continue
        row = session.execute(
            select(ParentChunk)
            .where(ParentChunk.version_id == version_id, ParentChunk.parent_id == parent_id)
        ).scalar_one_or_none()

        payload = {key: record.get(key) for key in extra_child_fields if key in record}
        if row is not None:
            seen_parent_ids.add(parent_id)
            metadata = dict(row.chunk_metadata or {})
            metadata.update(
                {
                    "retrieval_level": "parent",
                    "matched_child_id": record.get("child_id", ""),
                    "matched_child_preview": str(record.get("content") or "")[:220],
                    **payload,
                }
            )
            expanded.append(
                {
                    "retrieval_level": "parent",
                    "parent_id": parent_id,
                    "file_name": record.get("file_name", ""),
                    "source": record.get("file_name", ""),
                    "content": row.content,
                    "preview": row.content[:220],
                    "metadata": metadata,
                }
            )
        else:
            metadata = dict(record.get("metadata") or {})
            metadata.update({"retrieval_level": "child", "matched_child_id": record.get("child_id", "")})
            expanded.append({**record, "metadata": metadata})
        if len(expanded) >= top_k:
            break
    return expanded


def version_stats(session: Session, version_id: int) -> dict[str, Any]:
    document_count = session.execute(
        select(func.count()).select_from(DocumentRecord).where(DocumentRecord.version_id == version_id)
    ).scalar_one()
    parent_count = session.execute(
        select(func.count()).select_from(ParentChunk).where(ParentChunk.version_id == version_id)
    ).scalar_one()
    child_count = session.execute(
        select(func.count()).select_from(ChildChunk).where(ChildChunk.version_id == version_id)
    ).scalar_one()
    return {
        "document_count": document_count,
        "parent_count": parent_count,
        "child_count": child_count,
    }


def validate_version(session: Session, version_id: int) -> list[str]:
    """Post-build consistency checks. Empty list means the version is valid."""
    problems: list[str] = []
    orphan_children = session.execute(
        select(func.count())
        .select_from(ChildChunk)
        .outerjoin(ParentChunk, ChildChunk.parent_pk == ParentChunk.id)
        .where(ChildChunk.version_id == version_id, ParentChunk.id.is_(None))
    ).scalar_one()
    if orphan_children:
        problems.append(f"{orphan_children} child chunks without parent")

    records = session.execute(
        select(DocumentRecord).where(
            DocumentRecord.version_id == version_id,
            DocumentRecord.status == "indexed",
        )
    ).scalars().all()
    for record in records:
        actual_parents = session.execute(
            select(func.count())
            .select_from(ParentChunk)
            .where(ParentChunk.document_id == record.id)
        ).scalar_one()
        actual_children = session.execute(
            select(func.count())
            .select_from(ChildChunk)
            .where(ChildChunk.document_id == record.id)
        ).scalar_one()
        if record.parent_count and actual_parents != record.parent_count:
            problems.append(
                f"{record.file_name}: parent count mismatch (record={record.parent_count}, actual={actual_parents})"
            )
        if record.chunk_count and actual_children != record.chunk_count:
            problems.append(
                f"{record.file_name}: child count mismatch (record={record.chunk_count}, actual={actual_children})"
            )
    return problems


def set_version_source_manifest(session: Session, version_id: int, manifest: dict[str, Any]) -> None:
    session.execute(
        update(IndexVersion).where(IndexVersion.id == version_id).values(source_manifest=manifest)
    )
    session.flush()


def documents_snapshot(session: Session, version_id: int) -> dict[str, dict[str, Any]]:
    records = session.execute(
        select(DocumentRecord).where(DocumentRecord.version_id == version_id)
    ).scalars().all()
    return {
        record.file_name: {
            "file_hash": record.file_hash,
            "file_size": record.file_size,
            "modified_at": record.modified_at,
            "status": record.status,
            "parent_count": record.parent_count,
            "chunk_count": record.chunk_count,
            "error": record.error,
        }
        for record in records
    }
