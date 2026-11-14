from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings

from backend.core.config import EMBEDDING_MODEL_BACKEND, EMBEDDING_MODEL_NAME, LOCAL_EMBEDDING_MODEL
from backend.indexing.embedding_models import BgeM3OnnxEmbeddings


@lru_cache(maxsize=1)
def get_embedding() -> Embeddings:
    """Shared embedding instance for indexing and retrieval (same model, same vectors)."""
    from pathlib import Path

    from langchain_community.embeddings import HuggingFaceBgeEmbeddings

    local_model = Path(LOCAL_EMBEDDING_MODEL).expanduser() if LOCAL_EMBEDDING_MODEL else None
    model_name = str(local_model) if local_model and local_model.exists() else EMBEDDING_MODEL_NAME

    if model_name == "BAAI/bge-m3" and EMBEDDING_MODEL_BACKEND.lower() == "onnx":
        return BgeM3OnnxEmbeddings(model_name)

    return HuggingFaceBgeEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
        query_instruction="为文本生成向量表示用于文本检索",
    )
