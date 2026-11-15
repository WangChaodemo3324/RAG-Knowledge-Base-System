from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

METADATA_SCHEMA_VERSION = 5


def metadata_fields() -> list[str]:
    return [
        "source",
        "file_name",
        "file_stem",
        "file_path",
        "file_hash",
        "file_hash_short",
        "file_size",
        "file_type",
        "file_modified_at",
        "document_count",
        "chunk_level",
        "chunk_id",
        "chunk_index",
        "chunk_number",
        "chunk_total",
        "chunk_hash",
        "chunk_hash_short",
        "chunk_char_count",
        "chunk_preview",
        "chunking_strategy",
        "chunk_size",
        "chunk_overlap",
        "parent_chunk_size",
        "parent_chunk_overlap",
        "child_chunk_size",
        "child_chunk_overlap",
        "child_chunking_mode",
        "semantic_min_chunk_size",
        "chunk_separators",
        "parent_id",
        "parent_index",
        "parent_number",
        "parent_total",
        "parent_hash",
        "parent_hash_short",
        "parent_char_count",
        "parent_preview",
        "child_index_in_parent",
        "child_number_in_parent",
        "child_total_in_parent",
        "section_title",
        "page_number",
        "indexed_at",
        "metadata_schema_version",
    ]


class ChunkMetadataBuilder:
    """Adds stable, searchable metadata to chunks before vector insertion."""

    def prepare_chunks(
        self,
        file_path: Path,
        documents: list[Any],
        parents: list[Any],
        children: list[Any],
        fingerprint: dict[str, Any],
        indexed_at: str,
        chunk_settings: dict[str, Any],
    ) -> tuple[list[Any], list[str], list[dict[str, Any]], list[str]]:
        file_key = self._file_key(file_path)
        parent_total = len(parents)
        child_total = len(children)
        chunk_ids: list[str] = []
        parent_ids: list[str] = []
        parent_records: list[dict[str, Any]] = []
        children_per_parent = self._children_per_parent(children)

        for parent_index, parent in enumerate(parents):
            parent_id = self._parent_id(fingerprint["file_hash"], file_key, parent_index)
            parent_ids.append(parent_id)
            parent_metadata = self._parent_metadata(
                file_path=file_path,
                documents=documents,
                parent=parent,
                parent_id=parent_id,
                parent_index=parent_index,
                parent_total=parent_total,
                fingerprint=fingerprint,
                indexed_at=indexed_at,
                chunk_settings=chunk_settings,
                child_count=children_per_parent.get(parent_index, 0),
            )
            parent_records.append(
                {
                    "parent_id": parent_id,
                    "content": parent.page_content,
                    "metadata": parent_metadata,
                }
            )

        for index, chunk in enumerate(children):
            parent_index = int(chunk.metadata.get("parent_index") or 0)
            child_index_in_parent = int(chunk.metadata.get("child_index_in_parent") or 0)
            parent_id = self._parent_id(fingerprint["file_hash"], file_key, parent_index)
            chunk_hash = self._content_hash(chunk.page_content)
            chunk_id = f"{parent_id}-c{child_index_in_parent}"
            chunk_ids.append(chunk_id)
            metadata = self._clean_metadata(getattr(chunk, "metadata", {}))
            page_number = self._page_number(metadata)
            parent_record = parent_records[parent_index] if parent_index < len(parent_records) else {}
            parent_metadata = parent_record.get("metadata", {})
            metadata.update(
                {
                    "source": str(file_path),
                    "file_name": file_path.name,
                    "file_stem": file_path.stem,
                    "file_path": str(file_path),
                    "file_hash": fingerprint["file_hash"],
                    "file_hash_short": fingerprint["file_hash"][:12],
                    "file_size": fingerprint["file_size"],
                    "file_type": file_path.suffix.lower(),
                    "file_modified_at": fingerprint["modified_at"],
                    "document_count": len(documents),
                    "chunk_level": "child",
                    "chunk_id": chunk_id,
                    "chunk_index": index,
                    "chunk_number": index + 1,
                    "chunk_total": child_total,
                    "chunk_hash": chunk_hash,
                    "chunk_hash_short": chunk_hash[:12],
                    "chunk_char_count": len(chunk.page_content),
                    "chunk_preview": chunk.page_content[:120],
                    "chunking_strategy": chunk_settings["chunking_strategy"],
                    "chunk_size": chunk_settings["chunk_size"],
                    "chunk_overlap": chunk_settings["chunk_overlap"],
                    "parent_chunk_size": chunk_settings["parent_chunk_size"],
                    "parent_chunk_overlap": chunk_settings["parent_chunk_overlap"],
                    "child_chunk_size": chunk_settings["child_chunk_size"],
                    "child_chunk_overlap": chunk_settings["child_chunk_overlap"],
                    "child_chunking_mode": chunk_settings.get("child_chunking_mode", ""),
                    "semantic_min_chunk_size": chunk_settings.get("semantic_min_chunk_size", 0),
                    "chunk_separators": chunk_settings["chunk_separators"],
                    "parent_id": parent_id,
                    "parent_index": parent_index,
                    "parent_number": parent_index + 1,
                    "parent_total": parent_total,
                    "parent_hash": parent_metadata.get("parent_hash", ""),
                    "parent_hash_short": parent_metadata.get("parent_hash_short", ""),
                    "parent_char_count": parent_metadata.get("parent_char_count", 0),
                    "parent_preview": parent_metadata.get("parent_preview", ""),
                    "child_index_in_parent": child_index_in_parent,
                    "child_number_in_parent": child_index_in_parent + 1,
                    "child_total_in_parent": children_per_parent.get(parent_index, 0),
                    "section_title": self._section_title(chunk.page_content),
                    "indexed_at": indexed_at,
                    "metadata_schema_version": METADATA_SCHEMA_VERSION,
                }
            )
            if page_number is not None:
                metadata["page_number"] = page_number
            chunk.metadata = metadata
        return children, chunk_ids, parent_records, parent_ids

    def _parent_metadata(
        self,
        file_path: Path,
        documents: list[Any],
        parent: Any,
        parent_id: str,
        parent_index: int,
        parent_total: int,
        fingerprint: dict[str, Any],
        indexed_at: str,
        chunk_settings: dict[str, Any],
        child_count: int,
    ) -> dict[str, Any]:
        parent_hash = self._content_hash(parent.page_content)
        metadata = self._clean_metadata(getattr(parent, "metadata", {}))
        page_number = self._page_number(metadata)
        metadata.update(
            {
                "source": str(file_path),
                "file_name": file_path.name,
                "file_stem": file_path.stem,
                "file_path": str(file_path),
                "file_hash": fingerprint["file_hash"],
                "file_hash_short": fingerprint["file_hash"][:12],
                "file_size": fingerprint["file_size"],
                "file_type": file_path.suffix.lower(),
                "file_modified_at": fingerprint["modified_at"],
                "document_count": len(documents),
                "chunk_level": "parent",
                "chunk_id": parent_id,
                "chunk_index": parent_index,
                "chunk_number": parent_index + 1,
                "chunk_total": parent_total,
                "chunk_hash": parent_hash,
                "chunk_hash_short": parent_hash[:12],
                "chunk_char_count": len(parent.page_content),
                "chunk_preview": parent.page_content[:120],
                "chunking_strategy": chunk_settings["chunking_strategy"],
                "chunk_size": chunk_settings["chunk_size"],
                "chunk_overlap": chunk_settings["chunk_overlap"],
                "parent_chunk_size": chunk_settings["parent_chunk_size"],
                "parent_chunk_overlap": chunk_settings["parent_chunk_overlap"],
                "child_chunk_size": chunk_settings["child_chunk_size"],
                "child_chunk_overlap": chunk_settings["child_chunk_overlap"],
                "child_chunking_mode": chunk_settings.get("child_chunking_mode", ""),
                "semantic_min_chunk_size": chunk_settings.get("semantic_min_chunk_size", 0),
                "chunk_separators": chunk_settings["chunk_separators"],
                "parent_id": parent_id,
                "parent_index": parent_index,
                "parent_number": parent_index + 1,
                "parent_total": parent_total,
                "parent_hash": parent_hash,
                "parent_hash_short": parent_hash[:12],
                "parent_char_count": len(parent.page_content),
                "parent_preview": parent.page_content[:120],
                "child_total_in_parent": child_count,
                "section_title": self._section_title(parent.page_content),
                "indexed_at": indexed_at,
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
            }
        )
        if page_number is not None:
            metadata["page_number"] = page_number
        return metadata

    def _file_key(self, file_path: Path) -> str:
        return hashlib.sha256(str(file_path.resolve()).encode("utf-8")).hexdigest()[:12]

    def _parent_id(self, file_hash: str, file_key: str, parent_index: int) -> str:
        return f"{file_hash[:16]}-{file_key}-p{parent_index}"

    def _content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _clean_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned

    def _page_number(self, metadata: dict[str, Any]) -> int | None:
        page = metadata.get("page")
        if isinstance(page, bool):
            return None
        if isinstance(page, int):
            return page + 1
        if isinstance(page, str) and page.isdigit():
            return int(page) + 1
        return None

    def _section_title(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()[:120]
        return ""

    def _children_per_parent(self, children: list[Any]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for child in children:
            parent_index = int(child.metadata.get("parent_index") or 0)
            counts[parent_index] = counts.get(parent_index, 0) + 1
        return counts
