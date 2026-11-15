from __future__ import annotations

from typing import Any

import time

from backend.core import metrics
from backend.core.config import RERANK_MAX_LENGTH, RERANK_MODEL_NAME


class RerankService:
    """Cross-encoder reranker over child candidates."""

    def __init__(self, model_name: str = RERANK_MODEL_NAME, max_length: int = RERANK_MAX_LENGTH) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self.model: Any | None = None
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
            "rerank_load_error": self.load_error,
        }

    def _model(self) -> Any:
        if self.model is not None:
            return self.model
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name, max_length=self.max_length, device="cpu")
            self.load_error = ""
            return self.model
        except Exception as exc:
            self.load_error = str(exc)
            raise RuntimeError(f"Rerank model load failed: {exc}") from exc
