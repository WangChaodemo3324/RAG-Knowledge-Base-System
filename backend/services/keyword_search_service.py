from __future__ import annotations

import re
import threading
import time
from typing import Any

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select

from backend.db import session_scope
from backend.db.models import ChildChunk
from backend.indexing import pg_store

_SIGNATURE_CHECK_TTL_SECONDS = 1.5


class KeywordSearchService:
    """BM25 keyword retrieval over the ACTIVE index version's child chunks.

    The corpus is rebuilt in memory whenever the (version_id, child_count)
    signature changes, so keyword and vector retrieval always read the same
    committed version snapshot. Signature checks are rate-limited (TTL) to
    avoid two queries per search on a hot path.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._version_id: int | None = None
        self._child_count: int = -1
        self.children: list[dict[str, Any]] = []
        self.bm25: BM25Okapi | None = None
        self._last_check: float = 0.0

    def search(self, query: str, top_k: int = 5, file_name: str = "") -> list[dict[str, Any]]:
        self.ensure_loaded()
        with self._lock:
            if not self.bm25 or not self.children:
                return []

            tokenized_query = self.tokenize(query)
            if not tokenized_query:
                return []

            stage_started = time.perf_counter()
            scores = self.bm25.get_scores(tokenized_query)
            ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

            results: list[dict[str, Any]] = []
            for index in ranked_indices:
                score = float(scores[index])
                if score <= 0:
                    continue
                item = self.children[index]
                if file_name and item.get("file_name") != file_name:
                    continue
                metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
                content = str(item.get("content") or "")
                results.append(
                    {
                        "rank": len(results) + 1,
                        "score": score,
                        "retrieval_level": "child",
                        "child_id": item.get("child_id", ""),
                        "parent_id": item.get("parent_id", ""),
                        "file_name": item.get("file_name", ""),
                        "source": item.get("file_name", ""),
                        "content": content,
                        "preview": content[:220],
                        "metadata": metadata,
                    }
                )
                if len(results) >= top_k:
                    break
            from backend.core import metrics

            metrics.record_stage("bm25_ms", (time.perf_counter() - stage_started) * 1000)
            return results

    def ensure_loaded(self) -> None:
        now = time.monotonic()
        if now - self._last_check < _SIGNATURE_CHECK_TTL_SECONDS:
            return
        signature = self._active_signature()
        with self._lock:
            self._last_check = time.monotonic()
            if signature == (self._version_id, self._child_count):
                return
            version_id, _count = signature
            if version_id is None:
                self.children = []
                self.bm25 = None
                self._version_id = None
                self._child_count = 0
                return
            with session_scope() as session:
                corpus = pg_store.load_children_for_bm25(session, version_id)
            self.children = corpus
            self.bm25 = BM25Okapi([self.tokenize(str(item.get("content") or "")) for item in corpus]) if corpus else None
            self._version_id = version_id
            self._child_count = len(corpus)

    def _active_signature(self) -> tuple[int | None, int]:
        with session_scope() as session:
            active = pg_store.get_active_version(session)
            if active is None:
                return None, 0
            count = session.execute(
                select(func.count())
                .select_from(ChildChunk)
                .where(ChildChunk.version_id == active.id)
            ).scalar_one()
            return active.id, int(count)

    def tokenize(self, text: str) -> list[str]:
        tokens = jieba.lcut(str(text), cut_all=False)
        return [token.strip().lower() for token in tokens if self._keep_token(token)]

    def info(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "backend": "postgresql+pgvector",
            "version_id": self._version_id,
            "child_count": self._child_count,
            "keyword_index_ready": bool(self.bm25),
        }

    @staticmethod
    def _keep_token(token: str) -> bool:
        stripped = token.strip()
        if not stripped:
            return False
        return bool(re.search(r"[\w\u4e00-\u9fff]", stripped))
