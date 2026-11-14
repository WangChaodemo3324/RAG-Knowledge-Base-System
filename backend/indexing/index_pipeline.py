"""Versioned indexing pipeline (blue-green builds, no delete-before-build).

Replaces IndexService for writes:

- full build writes a NEW `building` version, validates it, then atomically
  flips `is_active`; the previous active version is retired but kept;
- incremental updates swap one document's chunks inside a single transaction
  (delete + insert commit together), so readers never observe a half-updated file;
- every task is recorded in index_tasks and survives crash recovery.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from backend.db import session_scope
from backend.indexing.chunk_metadata import METADATA_SCHEMA_VERSION, ChunkMetadataBuilder
from backend.indexing.document_processor import DocumentProcessor
from backend.indexing.embedding_provider import get_embedding
from backend.indexing import pg_store

_SCHEMA_VERSION = str(METADATA_SCHEMA_VERSION)

_INDEX_LOCK = threading.RLock()


class IndexPipelineError(RuntimeError):
    pass


class IndexPipeline:
    def __init__(
        self,
        data_dir: Path,
        embedding: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.processor = DocumentProcessor(data_dir)
        self.embedding = embedding or get_embedding()
        self.metadata_builder = ChunkMetadataBuilder()
        # injectable for tests (throwaway databases); defaults to the app engine
        self._session_factory = session_factory or session_scope

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            yield session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def full_build(self, reason: str = "") -> dict[str, Any]:
        with _INDEX_LOCK:
            return self._full_build_locked(reason)

    def add_or_update_file(self, file_path: Path, replace_existing: bool = True) -> dict[str, Any]:
        with _INDEX_LOCK:
            return self._incremental_locked(file_path, replace_existing)

    def ensure_bootstrapped(self) -> dict[str, Any] | None:
        """Startup safety: recover stale tasks; build v1 if no active version exists."""
        with self._session() as session:
            building = session.execute(
                sql_text("SELECT id FROM index_versions WHERE status = 'building'")
            ).all()
            stale_ids = [row[0] for row in building]
            pg_store.recover_stale_tasks(session, stale_ids)
            active = pg_store.get_active_version(session)
        if active is not None:
            return None
        return self.full_build(reason="bootstrap: no active index version")

    def version_overview(self) -> dict[str, Any]:
        with self._session() as session:
            active = pg_store.get_active_version(session)
            stats = pg_store.version_stats(session, active.id) if active else {}
            return {
                "active_version": {
                    "id": active.id,
                    "name": active.name,
                    "embedding_model": active.embedding_model,
                    "metadata_schema_version": active.metadata_schema_version,
                    "chunk_settings": active.chunk_settings,
                    "activated_at": active.activated_at.isoformat() if active.activated_at else "",
                }
                if active
                else None,
                "stats": stats,
                "versions": pg_store.list_versions(session),
            }

    # ------------------------------------------------------------------
    # Full build (blue-green)
    # ------------------------------------------------------------------

    def _full_build_locked(self, reason: str) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        version_name = f"v_{started_at.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
        chunk_settings = self.processor.chunk_settings()

        with self._session() as session:
            task = pg_store.start_task(session, "full_rebuild")
            version = pg_store.create_building_version(
                session,
                name=version_name,
                embedding_model=getattr(self.embedding, "model_name", "unknown"),
                chunk_settings=chunk_settings,
                metadata_schema_version=str(_SCHEMA_VERSION),
                notes=reason,
            )
            task_id, version_id = task.id, version.id

        indexed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        try:
            for file_path in self.processor.supported_files():
                try:
                    indexed.append(self._index_file_into_version(version_id, file_path, mode="full_rebuild"))
                except Exception as exc:  # noqa: BLE001
                    failed.append({"filename": file_path.name, "error": str(exc)})

            with self._session() as session:
                # an empty build must never replace a good active version —
                # e.g. an embedding-service outage failing every file silently
                if not indexed:
                    raise IndexPipelineError(
                        f"no files were indexed ({len(failed)} failed); refusing to activate empty version"
                    )
                problems = pg_store.validate_version(session, version_id)
                problems.extend(self._cross_check_problems(session, version_id, indexed))
                if problems:
                    raise IndexPipelineError("validation failed: " + "; ".join(problems))
                pg_store.set_version_source_manifest(
                    session,
                    version_id,
                    {item["file_name"]: item for item in indexed},
                )
                pg_store.activate_version(session, version_id)
                pg_store.finish_task(
                    session,
                    task_id,
                    succeeded=True,
                    message=f"built {version_name}: {len(indexed)} files, {len(failed)} failed",
                )
        except Exception as exc:
            with self._session() as session:
                pg_store.finish_task(session, task_id, succeeded=False, error=str(exc))
                pg_store.mark_version_failed(session, version_id, str(exc))
            raise

        return {
            "version": version_name,
            "version_id": version_id,
            "indexed_files": len(indexed),
            "failed_files": failed,
            "indexed": indexed,
        }

    def _index_file_into_version(self, version_id: int, file_path: Path, mode: str) -> dict[str, Any]:
        """Prepare + embed outside any DB transaction; write inside one transaction."""
        prepared = self._prepare_file(file_path)
        with self._session() as session:
            record = pg_store.upsert_document(
                session,
                version_id=version_id,
                file_name=file_path.name,
                file_hash=prepared["fingerprint"]["file_hash"],
                file_size=prepared["fingerprint"]["file_size"],
                modified_at=prepared["fingerprint"]["modified_at"],
                document_count=prepared["document_count"],
            )
            pg_store.delete_document_chunks(session, record)
            self._write_prepared(session, version_id, record, prepared)
        return {
            "file_name": file_path.name,
            "file_hash": prepared["fingerprint"]["file_hash"],
            "parent_count": prepared["parents_rowcount"],
            "chunk_count": prepared["children_rowcount"],
            "mode": mode,
        }

    # ------------------------------------------------------------------
    # Incremental swap into the ACTIVE version
    # ------------------------------------------------------------------

    def _incremental_locked(self, file_path: Path, replace_existing: bool) -> dict[str, Any]:
        prepared = self._prepare_file(file_path)
        # The task row, the old-chunk deletion and the new-chunk insertion all
        # commit (or roll back) together: a crash leaves no stale task and the
        # document keeps its previous chunks.
        with self._session() as session:
            version = pg_store.require_active_version(session)
            task = pg_store.start_task(session, "incremental", version_id=version.id)

            existing = pg_store.get_document(session, version.id, file_path.name)
            if existing is not None and existing.status == "indexed":
                unchanged = (
                    existing.file_hash == prepared["fingerprint"]["file_hash"]
                    and existing.chunk_count == prepared["children_rowcount"]
                    and version.chunk_settings == self.processor.chunk_settings()
                )
                if unchanged and replace_existing:
                    pg_store.finish_task(session, task.id, succeeded=True, message="unchanged, skipped")
                    return {"file_name": file_path.name, "status": "skipped"}

            record = pg_store.upsert_document(
                session,
                version_id=version.id,
                file_name=file_path.name,
                file_hash=prepared["fingerprint"]["file_hash"],
                file_size=prepared["fingerprint"]["file_size"],
                modified_at=prepared["fingerprint"]["modified_at"],
                document_count=prepared["document_count"],
            )
            pg_store.delete_document_chunks(session, record)
            self._write_prepared(session, version.id, record, prepared)
            pg_store.finish_task(session, task.id, succeeded=True, message="incremental swap committed")
            stats = pg_store.version_stats(session, version.id)
            snapshot = pg_store.documents_snapshot(session, version.id)

        return {
            "file_name": file_path.name,
            "status": "indexed",
            "parent_count": prepared["parents_rowcount"],
            "chunk_count": prepared["children_rowcount"],
            "total_stats": stats,
            "documents": snapshot,
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _prepare_file(self, file_path: Path) -> dict[str, Any]:
        file_path = file_path.resolve()
        fingerprint = self.processor.fingerprint(file_path)
        documents = self.processor.load_file(file_path)
        split_result = self.processor.split_documents(documents)
        chunk_settings = self.processor.chunk_settings()
        children, _chunk_ids, parent_records, _parent_ids = self.metadata_builder.prepare_chunks(
            file_path=file_path,
            documents=documents,
            parents=split_result.parents,
            children=split_result.children,
            fingerprint=fingerprint,
            indexed_at=pg_store.now_iso(),
            chunk_settings=chunk_settings,
        )
        if not children:
            raise IndexPipelineError(f"No text chunks generated from: {file_path}")

        parent_rows = [
            {
                "parent_id": parent["parent_id"],
                "parent_index": int(parent.get("metadata", {}).get("parent_index", index)),
                "content": parent["content"],
                "metadata": dict(parent.get("metadata") or {}),
            }
            for index, parent in enumerate(parent_records)
        ]
        child_rows = [
            {
                "child_id": child.metadata["chunk_id"],
                "child_index": int(child.metadata.get("chunk_index", index)),
                "parent_index": int(child.metadata.get("parent_index", 0)),
                "content": child.page_content,
                "embedding": None,  # filled by _embed_rows
                "metadata": dict(child.metadata or {}),
            }
            for index, child in enumerate(children)
        ]
        self._embed_rows(child_rows)
        return {
            "fingerprint": fingerprint,
            "chunk_settings": chunk_settings,
            "document_count": len(documents),
            "parent_rows": parent_rows,
            "child_rows": child_rows,
            "parents_rowcount": len(parent_rows),
            "children_rowcount": len(child_rows),
        }

    def _embed_rows(self, child_rows: list[dict[str, Any]]) -> None:
        texts = [row["content"] for row in child_rows]
        batch_size = 8
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self.embedding.embed_documents(texts[start : start + batch_size]))
        for row, vector in zip(child_rows, vectors):
            row["embedding"] = vector

    def _write_prepared(self, session: Session, version_id: int, record: Any, prepared: dict[str, Any]) -> None:
        pg_store.write_chunks(
            session,
            version_id,
            record,
            parents=prepared["parent_rows"],
            children=prepared["child_rows"],
        )

    def _cross_check_problems(
        self,
        session: Session,
        version_id: int,
        indexed: list[dict[str, Any]],
    ) -> list[str]:
        problems: list[str] = []
        expected_files = {item["file_name"] for item in indexed}
        snapshot = pg_store.documents_snapshot(session, version_id)
        for file_name in expected_files:
            record = snapshot.get(file_name)
            if record is None or record["status"] != "indexed":
                problems.append(f"{file_name}: missing indexed document record")
        return problems
