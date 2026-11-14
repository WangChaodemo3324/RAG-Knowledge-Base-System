from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_community.document_loaders import PyPDFLoader, TextLoader

from backend.core.config import DATA_DIR, FALLBACK_DATA_FILE, SUPPORTED_DOCUMENT_EXTENSIONS
from backend.indexing.chunking import ParentChildChunker, ParentChildChunks


class DocumentProcessor:
    """Loads source files and turns loader documents into raw chunks."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self.chunker = ParentChildChunker()

    def supported_files(self) -> list[Path]:
        if not self.data_dir.exists():
            return [FALLBACK_DATA_FILE] if FALLBACK_DATA_FILE.exists() else []
        return sorted(
            path
            for path in self.data_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
        )

    def load_file(self, file_path: Path) -> list[Any]:
        if file_path.suffix.lower() == ".pdf":
            return PyPDFLoader(str(file_path)).load()
        return TextLoader(str(file_path), encoding="utf-8").load()

    def split_documents(self, documents: list[Any]) -> ParentChildChunks:
        return self.chunker.split(documents)

    def chunk_settings(self) -> dict[str, Any]:
        return self.chunker.settings()

    def fingerprint(self, file_path: Path) -> dict[str, Any]:
        sha256 = hashlib.sha256()
        with file_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                sha256.update(chunk)
        stat = file_path.stat()
        return {
            "file_hash": sha256.hexdigest(),
            "file_size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
