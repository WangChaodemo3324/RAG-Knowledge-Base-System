from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import CHILD_STORE_FILE


class ChildStore:
    """Persists child chunks used by keyword retrieval."""

    def __init__(self, store_path: Path = CHILD_STORE_FILE) -> None:
        self.store_path = store_path
        self.data = self._load()

    def reset(self, collection_name: str) -> None:
        self.data = self._empty(collection_name)
        self.write()

    def upsert_documents(self, child_docs: list[Any]) -> None:
        children = self.data.setdefault("children", {})
        for child in child_docs:
            metadata = dict(getattr(child, "metadata", {}) or {})
            child_id = metadata.get("chunk_id")
            if not isinstance(child_id, str) or not child_id:
                continue
            children[child_id] = {
                "child_id": child_id,
                "parent_id": metadata.get("parent_id", ""),
                "file_name": metadata.get("file_name", ""),
                "source": metadata.get("source", ""),
                "content": getattr(child, "page_content", ""),
                "metadata": metadata,
            }
        self.write()

    def delete_record_children(self, record: dict[str, Any]) -> None:
        children = self.data.setdefault("children", {})
        child_ids = [child_id for child_id in record.get("chunk_ids", []) if isinstance(child_id, str)]
        if child_ids:
            for child_id in child_ids:
                children.pop(child_id, None)
            self.write()
            return

        file_name = record.get("file_name")
        if not file_name:
            return
        for child_id, child in list(children.items()):
            if child.get("file_name") == file_name:
                children.pop(child_id, None)
        self.write()

    def is_ready(self, collection_name: str, child_count: int) -> bool:
        return (
            self.store_path.exists()
            and self.data.get("collection_name") == collection_name
            and len(self.data.get("children", {})) >= child_count
        )

    def count(self) -> int:
        return len(self.data.get("children", {}))

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
        data.setdefault("children", {})
        return data

    def _empty(self, collection_name: str) -> dict[str, Any]:
        return {
            "version": 1,
            "collection_name": collection_name,
            "updated_at": self._now(),
            "children": {},
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
