from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from backend.core.config import PARENT_STORE_FILE


class ParentStore:
    """Persists parent chunks used to expand child vector hits."""

    def __init__(self, store_path: Path = PARENT_STORE_FILE) -> None:
        self.store_path = store_path
        self.data = self._load()

    def reset(self, collection_name: str) -> None:
        self.data = self._empty(collection_name)
        self.write()

    def upsert(self, records: list[dict[str, Any]]) -> None:
        parents = self.data.setdefault("parents", {})
        for record in records:
            parent_id = record.get("parent_id")
            if isinstance(parent_id, str) and parent_id:
                parents[parent_id] = record
        self.write()

    def delete_record_parents(self, record: dict[str, Any]) -> None:
        parents = self.data.setdefault("parents", {})
        parent_ids = [parent_id for parent_id in record.get("parent_ids", []) if isinstance(parent_id, str)]
        if parent_ids:
            for parent_id in parent_ids:
                parents.pop(parent_id, None)
            self.write()
            return

        file_name = record.get("file_name")
        if not file_name:
            return
        for parent_id, parent in list(parents.items()):
            metadata = parent.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("file_name") == file_name:
                parents.pop(parent_id, None)
        self.write()

    def expand_children(self, child_docs: list[Any], limit: int) -> list[Any]:
        expanded: list[Any] = []
        seen_parent_ids: set[str] = set()
        for child in child_docs:
            child_metadata = dict(getattr(child, "metadata", {}) or {})
            parent_id = str(child_metadata.get("parent_id") or "")
            if parent_id and parent_id in seen_parent_ids:
                continue

            parent = self.data.get("parents", {}).get(parent_id)
            if isinstance(parent, dict):
                seen_parent_ids.add(parent_id)
                metadata = dict(parent.get("metadata", {}) or {})
                metadata.update(
                    {
                        "retrieval_level": "parent",
                        "matched_child_id": child_metadata.get("chunk_id", ""),
                        "matched_child_index": child_metadata.get("chunk_index", ""),
                        "matched_child_preview": getattr(child, "page_content", "")[:220],
                    }
                )
                expanded.append(Document(page_content=str(parent.get("content") or ""), metadata=metadata))
            else:
                child_metadata["retrieval_level"] = "child"
                expanded.append(Document(page_content=getattr(child, "page_content", ""), metadata=child_metadata))

            if len(expanded) >= limit:
                break
        return expanded

    def expand_child_records(self, child_records: list[dict[str, Any]], limit: int) -> list[Any]:
        expanded: list[Any] = []
        seen_parent_ids: set[str] = set()
        for child in child_records:
            parent_id = str(child.get("parent_id") or "")
            if parent_id and parent_id in seen_parent_ids:
                continue

            parent = self.data.get("parents", {}).get(parent_id)
            child_metadata = child.get("metadata", {}) if isinstance(child.get("metadata"), dict) else {}
            if isinstance(parent, dict):
                seen_parent_ids.add(parent_id)
                metadata = dict(parent.get("metadata", {}) or {})
                metadata.update(
                    {
                        "retrieval_mode": "hybrid_rerank",
                        "retrieval_level": "parent",
                        "matched_child_id": child.get("child_id", ""),
                        "matched_child_index": child_metadata.get("chunk_index", ""),
                        "matched_child_preview": str(child.get("content") or "")[:220],
                        "rrf_score": child.get("rrf_score"),
                        "rerank_score": child.get("rerank_score"),
                        "rerank_model": child.get("rerank_model", ""),
                        "vector_rank": child.get("vector_rank"),
                        "bm25_rank": child.get("bm25_rank"),
                        "bm25_score": child.get("bm25_score"),
                        "retrievers": child.get("retrievers", []),
                    }
                )
                expanded.append(Document(page_content=str(parent.get("content") or ""), metadata=metadata))
            else:
                metadata = dict(child_metadata)
                metadata.update(
                    {
                        "retrieval_mode": "hybrid_rerank",
                        "retrieval_level": "child",
                        "matched_child_id": child.get("child_id", ""),
                        "rrf_score": child.get("rrf_score"),
                        "rerank_score": child.get("rerank_score"),
                        "rerank_model": child.get("rerank_model", ""),
                        "vector_rank": child.get("vector_rank"),
                        "bm25_rank": child.get("bm25_rank"),
                        "bm25_score": child.get("bm25_score"),
                        "retrievers": child.get("retrievers", []),
                    }
                )
                expanded.append(Document(page_content=str(child.get("content") or ""), metadata=metadata))

            if len(expanded) >= limit:
                break
        return expanded

    def is_ready(self, collection_name: str, parent_count: int) -> bool:
        return (
            self.store_path.exists()
            and self.data.get("collection_name") == collection_name
            and len(self.data.get("parents", {})) >= parent_count
        )

    def count(self) -> int:
        return len(self.data.get("parents", {}))

    def write(self) -> None:
        self.data["updated_at"] = self._now()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.store_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.store_path)

    def _load(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return self._empty("")
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty("")
        if not isinstance(data, dict):
            return self._empty("")
        data.setdefault("version", 1)
        data.setdefault("collection_name", "")
        data.setdefault("parents", {})
        return data

    def _empty(self, collection_name: str) -> dict[str, Any]:
        return {
            "version": 1,
            "collection_name": collection_name,
            "updated_at": self._now(),
            "parents": {},
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
