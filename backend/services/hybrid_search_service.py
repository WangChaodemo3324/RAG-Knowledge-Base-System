from __future__ import annotations

from typing import Any

from backend.knowledge.knowledge_base import KnowledgeBase
from backend.services.keyword_search_service import KeywordSearchService


class HybridSearchService:
    """Combines vector and BM25 child candidates with RRF."""

    def __init__(self, knowledge_base: KnowledgeBase, keyword_search: KeywordSearchService) -> None:
        self.knowledge_base = knowledge_base
        self.keyword_search = keyword_search

    def search(
        self,
        query: str,
        top_k: int = 10,
        vector_top_k: int = 10,
        keyword_top_k: int = 10,
        rrf_k: int = 60,
        file_name: str = "",
    ) -> list[dict[str, Any]]:
        vector_candidates = self._vector_candidates(query, vector_top_k, file_name=file_name)
        keyword_candidates = self.keyword_search.search(query, keyword_top_k, file_name=file_name)
        merged: dict[str, dict[str, Any]] = {}

        self._add_ranked_candidates(merged, vector_candidates, "vector", rrf_k)
        self._add_ranked_candidates(merged, keyword_candidates, "bm25", rrf_k)

        results = sorted(merged.values(), key=lambda item: item["rrf_score"], reverse=True)[:top_k]
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank
        return results

    def _vector_candidates(self, query: str, top_k: int, file_name: str = "") -> list[dict[str, Any]]:
        docs = self.knowledge_base.search_children(query, top_k, file_name=file_name)
        candidates: list[dict[str, Any]] = []
        for rank, doc in enumerate(docs, start=1):
            metadata = dict(getattr(doc, "metadata", {}) or {})
            content = getattr(doc, "page_content", "")
            candidates.append(
                {
                    "rank": rank,
                    "retrieval_level": "child",
                    "child_id": metadata.get("chunk_id", ""),
                    "parent_id": metadata.get("parent_id", ""),
                    "file_name": metadata.get("file_name", ""),
                    "source": metadata.get("file_name", ""),
                    "content": content,
                    "preview": content[:220],
                    "metadata": metadata,
                }
            )
        return candidates

    def _add_ranked_candidates(
        self,
        merged: dict[str, dict[str, Any]],
        candidates: list[dict[str, Any]],
        retriever: str,
        rrf_k: int,
    ) -> None:
        for rank, candidate in enumerate(candidates, start=1):
            child_id = str(candidate.get("child_id") or "")
            if not child_id:
                continue
            item = merged.setdefault(child_id, self._base_candidate(candidate))
            item["rrf_score"] += 1.0 / (rrf_k + rank)
            item[f"{retriever}_rank"] = rank
            if "retrievers" not in item:
                item["retrievers"] = []
            item["retrievers"].append(retriever)
            if retriever == "bm25":
                item["bm25_score"] = float(candidate.get("score") or 0.0)

    def _base_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "rank": 0,
            "rrf_score": 0.0,
            "retrieval_level": "child",
            "child_id": candidate.get("child_id", ""),
            "parent_id": candidate.get("parent_id", ""),
            "file_name": candidate.get("file_name", "") or candidate.get("source", ""),
            "source": candidate.get("source", "") or candidate.get("file_name", ""),
            "content": candidate.get("content", ""),
            "preview": candidate.get("preview", ""),
            "metadata": candidate.get("metadata", {}) if isinstance(candidate.get("metadata"), dict) else {},
            "vector_rank": None,
            "bm25_rank": None,
            "bm25_score": None,
            "retrievers": [],
        }
