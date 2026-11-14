from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from backend.core.config import CHILD_STORE_FILE


class KeywordSearchService:
    """BM25 keyword retrieval over child chunks only."""

    def __init__(self, child_store_path: Path = CHILD_STORE_FILE) -> None:
        self.child_store_path = child_store_path
        self.children: list[dict[str, Any]] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        self._loaded_mtime: float | None = None
        self.load_index()

    def search(self, query: str, top_k: int = 5, file_name: str = "") -> list[dict[str, Any]]:
        self.reload_if_changed()
        if not self.bm25 or not self.children:
            return []

        tokenized_query = self.tokenize(query)
        if not tokenized_query:
            return []

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
        return results

    def tokenize(self, text: str) -> list[str]:
        tokens = jieba.lcut(str(text), cut_all=False)
        return [token.strip().lower() for token in tokens if self._keep_token(token)]

    def load_index(self) -> None:
        if not self.child_store_path.exists():
            self.children = []
            self.tokenized_corpus = []
            self.bm25 = None
            self._loaded_mtime = None
            return

        data = json.loads(self.child_store_path.read_text(encoding="utf-8"))
        raw_children = data.get("children", {})
        if isinstance(raw_children, dict):
            self.children = list(raw_children.values())
        elif isinstance(raw_children, list):
            self.children = raw_children
        else:
            self.children = []

        corpus = [str(item.get("content") or "") for item in self.children]
        self.tokenized_corpus = [self.tokenize(text) for text in corpus]
        self.bm25 = BM25Okapi(self.tokenized_corpus) if self.tokenized_corpus else None
        self._loaded_mtime = self.child_store_path.stat().st_mtime

    def reload_if_changed(self) -> None:
        if not self.child_store_path.exists():
            if self.children:
                self.load_index()
            return
        current_mtime = self.child_store_path.stat().st_mtime
        if self._loaded_mtime != current_mtime:
            self.load_index()

    def info(self) -> dict[str, Any]:
        self.reload_if_changed()
        return {
            "child_store_path": str(self.child_store_path),
            "child_count": len(self.children),
            "keyword_index_ready": bool(self.bm25),
        }

    def _keep_token(self, token: str) -> bool:
        stripped = token.strip()
        if not stripped:
            return False
        return bool(re.search(r"[\w\u4e00-\u9fff]", stripped))
