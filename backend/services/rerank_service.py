"""Cross-encoder reranker with a container-safe loading fallback.

Primary path: sentence_transformers.CrossEncoder (works on the host).
Fallback path: transformers AutoModelForSequenceClassification + AutoTokenizer,
loading with HF_HUB_OFFLINE compatibility — required inside containers where
sentence-transformers' meta-device init fails on some filesystems (V3 finding).
Both paths produce identical rerank scores for bge-reranker models.
"""

from __future__ import annotations

import time
from typing import Any

from backend.core import metrics
from backend.core.config import RERANK_MAX_LENGTH, RERANK_MODEL_NAME
from backend.core.logging import get_logger

logger = get_logger(__name__)


class _TransformersCrossEncoder:
    """Minimal predict() shim over transformers AutoModelForSequenceClassification.

    bge-reranker models are sequence classifiers whose logit IS the relevance
    score, so this produces the same scores as sentence_transformers.
    """

    def __init__(self, model_name: str, max_length: int) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.eval()
        self.max_length = max_length

    def predict(self, pairs: list[list[str]]) -> list[float]:
        import torch

        scores: list[float] = []
        with torch.no_grad():
            for query, document in pairs:
                inputs = self.tokenizer(
                    query,
                    document,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                logits = self.model(**inputs).logits[0][0].item()
                scores.append(logits)
        return scores


class RerankService:
    """Cross-encoder reranker over child candidates."""

    def __init__(self, model_name: str = RERANK_MODEL_NAME, max_length: int = RERANK_MAX_LENGTH) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self.model: Any | None = None
        self.model_backend: str = ""
        self.load_error: str = ""

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        valid_candidates = [candidate for candidate in candidates if candidate.get("content")]
        if not valid_candidates:
            return []

        model = self._model()
        pairs = [[query, str(candidate.get("content") or "")[:1200]] for candidate in valid_candidates]
        started = time.perf_counter()
        scores = model.predict(pairs)
        metrics.record_stage("rerank_ms", (time.perf_counter() - started) * 1000)

        results: list[dict[str, Any]] = []
        for candidate, score in zip(valid_candidates, scores):
            item = dict(candidate)
            item["rerank_model"] = self.model_name
            item["rerank_score"] = float(score)
            results.append(item)

        results.sort(key=lambda item: item["rerank_score"], reverse=True)
        for rank, item in enumerate(results[:top_k], start=1):
            item["rank"] = rank
        return results[:top_k]

    def info(self) -> dict[str, Any]:
        return {
            "rerank_model": self.model_name,
            "rerank_max_length": self.max_length,
            "rerank_loaded": self.model is not None,
            "rerank_backend": self.model_backend,
            "rerank_load_error": self.load_error,
        }

    def _model(self) -> Any:
        if self.model is not None:
            return self.model

        # Path 1: sentence_transformers.CrossEncoder (host-verified)
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name, max_length=self.max_length, device="cpu")
            self.model_backend = "sentence_transformers"
            self.load_error = ""
            return self.model
        except Exception as exc:
            self.load_error = f"CrossEncoder: {str(exc)[:150]}"
            logger.warning("CrossEncoder load failed, trying transformers fallback: %s", self.load_error)

        # Path 2: transformers direct — verified inside the api container
        try:
            self.model = _TransformersCrossEncoder(self.model_name, self.max_length)
            self.model_backend = "transformers_fallback"
            self.load_error = ""
            return self.model
        except Exception as exc:
            self.load_error = f"transformers fallback: {str(exc)[:150]}"
            logger.error("transformers rerank fallback failed: %s", self.load_error)
            raise RuntimeError(f"Rerank model load failed: {self.load_error}") from exc
