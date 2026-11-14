from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings

from backend.core.config import CHROMA_DIR, EMBEDDING_MODEL_BACKEND, EMBEDDING_MODEL_NAME, LOCAL_EMBEDDING_MODEL
from backend.indexing.embedding_models import BgeM3OnnxEmbeddings


class VectorStoreManager:
    """Owns Chroma persistence and low-level vector operations."""

    def __init__(self, persist_dir: Path = CHROMA_DIR, collection_name: str = "rag_documents") -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        local_model = Path(LOCAL_EMBEDDING_MODEL).expanduser() if LOCAL_EMBEDDING_MODEL else None
        self.embedding_model_name = str(local_model) if local_model and local_model.exists() else EMBEDDING_MODEL_NAME
        self.embedding = self._build_embedding()
        self.db = self._new_store(collection_name)

    def use_collection(self, collection_name: str) -> None:
        self.collection_name = collection_name
        self.db = self._new_store(collection_name)

    def delete_collection(self, collection_name: str) -> None:
        try:
            self.db._client.delete_collection(collection_name)
        except Exception:
            pass

    def add_documents(self, chunks: list[Any], ids: list[str]) -> None:
        self.db.add_documents(chunks, ids=ids)

    def delete_record_chunks(self, record: dict[str, Any]) -> None:
        chunk_ids = [chunk_id for chunk_id in record.get("chunk_ids", []) if isinstance(chunk_id, str)]
        if chunk_ids:
            self.db.delete(ids=chunk_ids)
            return

        file_name = record.get("file_name")
        if file_name:
            self.db._collection.delete(where={"file_name": file_name})

    def search(self, query: str, top_k: int = 4, file_name: str = "") -> list[Any]:
        search_filter = {"file_name": file_name} if file_name else None
        return self.db.similarity_search(query, k=top_k, filter=search_filter)

    def count(self) -> int:
        try:
            return int(self.db._collection.count())
        except Exception:
            return 0

    def _new_store(self, collection_name: str) -> Chroma:
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        return Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding,
            persist_directory=str(self.persist_dir),
        )

    def _build_embedding(self) -> Embeddings:
        if self.embedding_model_name == "BAAI/bge-m3" and EMBEDDING_MODEL_BACKEND.lower() == "onnx":
            return BgeM3OnnxEmbeddings(self.embedding_model_name)

        return HuggingFaceBgeEmbeddings(
            model_name=self.embedding_model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
            query_instruction="为文本生成向量表示用于文本检索",
        )
