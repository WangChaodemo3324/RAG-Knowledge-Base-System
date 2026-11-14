from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import CHROMA_COLLECTION_NAME, CHROMA_DIR, DATA_DIR, MANIFEST_FILE


class ManifestStore:
    """Reads and writes file indexing state."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        persist_dir: Path = CHROMA_DIR,
        manifest_path: Path = MANIFEST_FILE,
        embedding_model_name: str = "",
    ) -> None:
        self.data_dir = data_dir
        self.persist_dir = persist_dir
        self.manifest_path = manifest_path
        self.embedding_model_name = embedding_model_name
        self.data = self._load()

    @property
    def collection_name(self) -> str:
        return str(self.data.get("collection_name") or CHROMA_COLLECTION_NAME)

    @property
    def exists(self) -> bool:
        return self.manifest_path.exists()

    def record(self, file_name: str) -> dict[str, Any] | None:
        value = self.data.get("files", {}).get(file_name)
        return value if isinstance(value, dict) else None

    def set_record(self, file_name: str, record: dict[str, Any]) -> None:
        self.data.setdefault("files", {})[file_name] = record
        self.write()

    def reset(self, collection_name: str) -> None:
        self.data = self._empty(collection_name)
        self.write()

    def write(self) -> None:
        self.data["updated_at"] = self._now()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.manifest_path)

    def indexed_chunk_count(self) -> int:
        return sum(
            int(record.get("chunk_count") or 0)
            for record in self.data.get("files", {}).values()
            if record.get("status") == "indexed"
        )

    def indexed_parent_count(self) -> int:
        return sum(
            int(record.get("parent_count") or 0)
            for record in self.data.get("files", {}).values()
            if record.get("status") == "indexed"
        )

    def uses_metadata_schema(self, version: int) -> bool:
        records = [
            record
            for record in self.data.get("files", {}).values()
            if isinstance(record, dict) and record.get("status") == "indexed"
        ]
        return bool(records) and all(record.get("metadata_schema_version") == version for record in records)

    def uses_chunk_settings(self, settings: dict[str, Any]) -> bool:
        records = [
            record
            for record in self.data.get("files", {}).values()
            if isinstance(record, dict) and record.get("status") == "indexed"
        ]
        return bool(records) and all(
            all(record.get(key) == value for key, value in settings.items())
            for record in records
        )

    def uses_embedding_model(self) -> bool:
        return self.data.get("embedding_model") == self.embedding_model_name

    def info(self, vector_count: int) -> dict[str, Any]:
        records = sorted(self.data.get("files", {}).values(), key=lambda item: item.get("file_name", ""))
        indexed_records = [record for record in records if record.get("status") == "indexed"]
        public_records: list[dict[str, Any]] = []
        for record in records:
            public_record = {key: value for key, value in record.items() if key not in {"chunk_ids", "parent_ids"}}
            public_record["chunk_id_count"] = len(record.get("chunk_ids", []))
            public_record["parent_id_count"] = len(record.get("parent_ids", []))
            public_records.append(public_record)
        return {
            "data_dir": str(self.data_dir),
            "data_files": [record["file_name"] for record in indexed_records],
            "document_count": sum(int(record.get("document_count") or 0) for record in indexed_records),
            "parent_count": sum(int(record.get("parent_count") or 0) for record in indexed_records),
            "chunk_count": sum(int(record.get("chunk_count") or 0) for record in indexed_records),
            "embedding_model": self.embedding_model_name,
            "persist_dir": str(self.persist_dir),
            "manifest_path": str(self.manifest_path),
            "collection_name": self.collection_name,
            "vector_count": vector_count,
            "indexed_files": public_records,
        }

    def _load(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return self._empty(CHROMA_COLLECTION_NAME)
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty(CHROMA_COLLECTION_NAME)
        if not isinstance(data, dict):
            return self._empty(CHROMA_COLLECTION_NAME)
        data.setdefault("files", {})
        data.setdefault("version", 1)
        data["data_dir"] = str(self.data_dir)
        data["persist_dir"] = str(self.persist_dir)
        data["manifest_path"] = str(self.manifest_path)
        data["collection_name"] = str(data.get("collection_name") or CHROMA_COLLECTION_NAME)
        data.setdefault("embedding_model", self.embedding_model_name)
        return data

    def _empty(self, collection_name: str) -> dict[str, Any]:
        return {
            "version": 1,
            "data_dir": str(self.data_dir),
            "persist_dir": str(self.persist_dir),
            "manifest_path": str(self.manifest_path),
            "collection_name": collection_name,
            "embedding_model": self.embedding_model_name,
            "updated_at": self._now(),
            "files": {},
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
