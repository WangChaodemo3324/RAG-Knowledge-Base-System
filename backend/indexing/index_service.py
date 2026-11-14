from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import (
    CHILD_STORE_FILE,
    CHROMA_COLLECTION_NAME,
    CHROMA_DIR,
    DATA_DIR,
    MANIFEST_FILE,
    PARENT_STORE_FILE,
)
from backend.indexing.chunk_metadata import METADATA_SCHEMA_VERSION, ChunkMetadataBuilder
from backend.indexing.child_store import ChildStore
from backend.indexing.document_processor import DocumentProcessor
from backend.indexing.index_manifest import ManifestStore
from backend.indexing.index_records import (
    failed_record,
    indexed_record,
    indexed_response,
    is_unchanged,
    rebuild_response,
    skipped_response,
)
from backend.indexing.parent_store import ParentStore
from backend.indexing.vector_store import VectorStoreManager


class IndexService:
    """Coordinates offline indexing; specialized work lives in smaller modules."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        persist_dir: Path = CHROMA_DIR,
        manifest_path: Path = MANIFEST_FILE,
    ) -> None:
        self.data_dir = data_dir
        self.processor = DocumentProcessor(data_dir)
        self.vector_store = VectorStoreManager(persist_dir)
        self.manifest = ManifestStore(
            data_dir=data_dir,
            persist_dir=persist_dir,
            manifest_path=manifest_path,
            embedding_model_name=self.vector_store.embedding_model_name,
        )
        self.vector_store.use_collection(self.manifest.collection_name)
        self.parent_store = ParentStore(PARENT_STORE_FILE)
        self.child_store = ChildStore(CHILD_STORE_FILE)
        self.metadata_builder = ChunkMetadataBuilder()
        self._load_or_build()

    def index_file(self, file_path: Path, replace_existing: bool = True, mode: str = "incremental") -> dict[str, Any]:
        file_path = file_path.resolve()
        indexed_at = self._now()
        fingerprint = self.processor.fingerprint(file_path)
        chunk_settings = self.processor.chunk_settings()
        previous = self.manifest.record(file_path.name)

        if is_unchanged(previous, fingerprint, chunk_settings):
            return skipped_response(file_path.name, previous, self.info())

        if previous and replace_existing:
            self.vector_store.delete_record_chunks(previous)
            self.parent_store.delete_record_parents(previous)
            self.child_store.delete_record_children(previous)

        try:
            documents = self.processor.load_file(file_path)
            split_result = self.processor.split_documents(documents)
            chunks, chunk_ids, parent_records, parent_ids = self.metadata_builder.prepare_chunks(
                file_path=file_path,
                documents=documents,
                parents=split_result.parents,
                children=split_result.children,
                fingerprint=fingerprint,
                indexed_at=indexed_at,
                chunk_settings=chunk_settings,
            )
            if not chunks:
                raise RuntimeError(f"No text chunks generated from: {file_path}")
            self.vector_store.add_documents(chunks, chunk_ids)
            self.child_store.upsert_documents(chunks)
            self.parent_store.upsert(parent_records)
            record = indexed_record(
                file_path,
                fingerprint,
                indexed_at,
                mode,
                len(documents),
                len(chunks),
                chunk_ids,
                len(parent_records),
                parent_ids,
                chunk_settings,
            )
        except Exception as exc:
            record = failed_record(file_path, fingerprint, indexed_at, mode, exc, chunk_settings)
            self.manifest.set_record(file_path.name, record)
            raise

        self.manifest.set_record(file_path.name, record)
        return indexed_response(file_path, mode, len(documents), len(chunks), len(parent_records), self.info())

    def full_rebuild(self) -> dict[str, Any]:
        old_collection_name = self.manifest.collection_name
        self.vector_store.delete_collection(old_collection_name)

        collection_name = f"{CHROMA_COLLECTION_NAME}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        self.vector_store.use_collection(collection_name)
        self.manifest.reset(collection_name)
        self.parent_store.reset(collection_name)
        self.child_store.reset(collection_name)

        indexed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for file_path in self.processor.supported_files():
            try:
                indexed.append(self.index_file(file_path, replace_existing=False, mode="full_rebuild"))
            except Exception as exc:
                failed.append({"filename": file_path.name, "error": str(exc)})

        info = self.info()
        return rebuild_response(info, len(indexed), failed, self.manifest.manifest_path, self.vector_store.persist_dir)

    def search(self, query: str, top_k: int = 4, file_name: str = "") -> list[Any]:
        child_docs = self.vector_store.search(query, max(top_k * 3, top_k), file_name=file_name)
        return self.parent_store.expand_children(child_docs, top_k)

    def search_children(self, query: str, top_k: int = 10, file_name: str = "") -> list[Any]:
        return self.vector_store.search(query, top_k, file_name=file_name)

    def expand_child_records(self, child_records: list[dict[str, Any]], top_k: int = 4) -> list[Any]:
        return self.parent_store.expand_child_records(child_records, top_k)

    def info(self) -> dict[str, Any]:
        info = self.manifest.info(self.vector_store.count())
        info["parent_store_path"] = str(self.parent_store.store_path)
        info["parent_store_count"] = self.parent_store.count()
        info["child_store_path"] = str(self.child_store.store_path)
        info["child_store_count"] = self.child_store.count()
        return info

    def _load_or_build(self) -> None:
        if (
            self.manifest.exists
            and self.vector_store.count() > 0
            and self.manifest.uses_embedding_model()
            and self.manifest.uses_metadata_schema(METADATA_SCHEMA_VERSION)
            and self.manifest.uses_chunk_settings(self.processor.chunk_settings())
            and self.parent_store.is_ready(self.manifest.collection_name, self.manifest.indexed_parent_count())
            and self.child_store.is_ready(self.manifest.collection_name, self.manifest.indexed_chunk_count())
        ):
            return
        self.full_rebuild()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
