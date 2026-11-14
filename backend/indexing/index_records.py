from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.indexing.chunk_metadata import METADATA_SCHEMA_VERSION, metadata_fields


def is_unchanged(
    previous: dict[str, Any] | None,
    fingerprint: dict[str, Any],
    chunk_settings: dict[str, Any],
) -> bool:
    return bool(
        previous
        and previous.get("file_hash") == fingerprint["file_hash"]
        and previous.get("status") == "indexed"
        and previous.get("metadata_schema_version") == METADATA_SCHEMA_VERSION
        and all(previous.get(key) == value for key, value in chunk_settings.items())
    )


def indexed_record(
    file_path: Path,
    fingerprint: dict[str, Any],
    indexed_at: str,
    mode: str,
    document_count: int,
    chunk_count: int,
    chunk_ids: list[str],
    parent_count: int,
    parent_ids: list[str],
    chunk_settings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "file_hash": fingerprint["file_hash"],
        "file_size": fingerprint["file_size"],
        "modified_at": fingerprint["modified_at"],
        "indexed_at": indexed_at,
        "status": "indexed",
        "index_mode": mode,
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "metadata_fields": metadata_fields(),
        **chunk_settings,
        "document_count": document_count,
        "parent_count": parent_count,
        "chunk_count": chunk_count,
        "chunk_ids": chunk_ids,
        "parent_ids": parent_ids,
    }


def failed_record(
    file_path: Path,
    fingerprint: dict[str, Any],
    indexed_at: str,
    mode: str,
    exc: Exception,
    chunk_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        **fingerprint,
        "indexed_at": indexed_at,
        "status": "failed",
        "index_mode": mode,
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "metadata_fields": metadata_fields(),
        **(chunk_settings or {}),
        "error": str(exc),
        "document_count": 0,
        "parent_count": 0,
        "chunk_count": 0,
        "chunk_ids": [],
        "parent_ids": [],
    }


def indexed_response(
    file_path: Path,
    mode: str,
    document_count: int,
    chunk_count: int,
    parent_count: int,
    info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "filename": file_path.name,
        "status": "indexed",
        "index_mode": mode,
        "document_count": document_count,
        "parent_count": parent_count,
        "chunk_count": chunk_count,
        "total_document_count": info["document_count"],
        "total_parent_count": info["parent_count"],
        "total_chunk_count": info["chunk_count"],
        "data_files": info["data_files"],
        "message": "文件已入库。",
    }


def skipped_response(filename: str, previous: dict[str, Any] | None, info: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": filename,
        "status": "skipped",
        "index_mode": "skip_unchanged",
        "document_count": int((previous or {}).get("document_count") or 0),
        "parent_count": int((previous or {}).get("parent_count") or 0),
        "chunk_count": int((previous or {}).get("chunk_count") or 0),
        "total_document_count": info["document_count"],
        "total_parent_count": info["parent_count"],
        "total_chunk_count": info["chunk_count"],
        "data_files": info["data_files"],
        "message": "文件内容未变化，跳过重复入库。",
    }


def rebuild_response(
    info: dict[str, Any],
    indexed_count: int,
    failed_files: list[dict[str, Any]],
    manifest_path: Path,
    persist_dir: Path,
) -> dict[str, Any]:
    return {
        "rebuilt": True,
        "index_mode": "full_rebuild",
        "indexed_files": indexed_count,
        "failed_files": failed_files,
        "document_count": info["document_count"],
        "parent_count": info["parent_count"],
        "chunk_count": info["chunk_count"],
        "data_files": info["data_files"],
        "manifest_path": str(manifest_path),
        "persist_dir": str(persist_dir),
        "message": "知识库已全量重建。",
    }
