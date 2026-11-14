from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.config import DATA_DIR
from backend.indexing.index_service import IndexService
from backend.knowledge.source_utils import doc_to_source


class KnowledgeBase:
    """Online retrieval facade backed by the offline IndexService."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.index = IndexService(data_dir)

    @property
    def data_dir(self) -> Path:
        return self.index.data_dir

    def search(self, query: str, top_k: int = 4, file_name: str = "") -> list[dict[str, Any]]:
        docs = self.index.search(query, top_k, file_name=file_name)
        return [doc_to_source(doc, i + 1) for i, doc in enumerate(docs)]

    def search_children(self, query: str, top_k: int = 10, file_name: str = "") -> list[Any]:
        return self.index.search_children(query, top_k, file_name=file_name)

    def expand_child_candidates(self, candidates: list[dict[str, Any]], top_k: int = 4) -> list[dict[str, Any]]:
        docs = self.index.expand_child_records(candidates, top_k)
        return [doc_to_source(doc, i + 1) for i, doc in enumerate(docs)]

    def add_file(self, file_path: Path, replace_existing: bool = True) -> dict[str, Any]:
        return self.index.index_file(file_path, replace_existing=replace_existing, mode="incremental")

    def rebuild(self) -> dict[str, Any]:
        return self.index.full_rebuild()

    def info(self) -> dict[str, Any]:
        return self.index.info()
