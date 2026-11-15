from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from backend.core import metrics
from backend.core.config import DATA_DIR
from backend.db import session_scope
from backend.indexing import pg_store
from backend.indexing.embedding_provider import get_embedding
from backend.indexing.index_pipeline import IndexPipeline
from backend.knowledge.source_utils import doc_to_source

_CHILD_SCORE_FIELDS = (
    "rrf_score",
    "rerank_score",
    "rerank_model",
    "vector_rank",
    "bm25_rank",
    "retrievers",
    "retrieval_mode",
)


class KnowledgeBase:
    """Online retrieval facade backed by PostgreSQL + pgvector (IndexPipeline writes)."""

    def __init__(self, data_dir: Path = DATA_DIR, embedding: Any | None = None) -> None:
        self.data_dir = data_dir
        self.pipeline = IndexPipeline(data_dir, embedding=embedding)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 4, file_name: str = "") -> list[dict[str, Any]]:
        query_embedding = get_embedding().embed_query(query)
        with session_scope() as session:
            version = pg_store.require_active_version(session)
            candidates = pg_store.search_children(
                session, version.id, query_embedding, top_k=max(top_k * 3, top_k), file_name=file_name
            )
            expanded = pg_store.expand_children_to_parents(
                session, version.id, candidates, top_k=top_k, extra_child_fields=_CHILD_SCORE_FIELDS
            )
        return [doc_to_source(item, i + 1) for i, item in enumerate(expanded)]

    def search_children(self, query: str, top_k: int = 10, file_name: str = "") -> list[dict[str, Any]]:
        started = time.perf_counter()
        query_embedding = get_embedding().embed_query(query)
        metrics.record_stage("embedding_ms", (time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        with session_scope() as session:
            version = pg_store.require_active_version(session)
            results = pg_store.search_children(session, version.id, query_embedding, top_k=top_k, file_name=file_name)
        metrics.record_stage("vector_search_ms", (time.perf_counter() - started) * 1000)
        return results

    def expand_child_candidates(self, candidates: list[dict[str, Any]], top_k: int = 4) -> list[dict[str, Any]]:
        with session_scope() as session:
            version = pg_store.require_active_version(session)
            expanded = pg_store.expand_children_to_parents(
                session, version.id, candidates, top_k=top_k, extra_child_fields=_CHILD_SCORE_FIELDS
            )
        return [doc_to_source(item, i + 1) for i, item in enumerate(expanded)]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add_file(self, file_path: Path, replace_existing: bool = True) -> dict[str, Any]:
        return self.pipeline.add_or_update_file(Path(file_path), replace_existing=replace_existing)

    def rebuild(self) -> dict[str, Any]:
        return self.pipeline.full_build(reason="manual rebuild via API")

    def ensure_bootstrapped(self) -> dict[str, Any] | None:
        return self.pipeline.ensure_bootstrapped()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        overview = self.pipeline.version_overview()
        stats = overview.get("stats") or {}
        active = overview.get("active_version")
        return {
            "backend": "postgresql+pgvector",
            "active_version": active,
            "versions": overview.get("versions", []),
            "document_count": stats.get("document_count", 0),
            "parent_count": stats.get("parent_count", 0),
            "chunk_count": stats.get("child_count", 0),
            "vector_count": stats.get("child_count", 0),
            "embedding_model": (active or {}).get("embedding_model", ""),
        }
