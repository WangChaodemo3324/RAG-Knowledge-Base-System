from __future__ import annotations

from typing import Any

from backend.services.routing.route_schema import EvidenceDecision


class EvidenceChecker:
    """Judge whether retrieved KB candidates are strong enough to answer from KB."""

    def __init__(self, min_content_length: int = 80, score_threshold: float = 0.45) -> None:
        self.min_content_length = min_content_length
        self.score_threshold = score_threshold

    def check(self, results: Any) -> EvidenceDecision:
        if not isinstance(results, list) or not results:
            return EvidenceDecision(False, "知识库没有返回候选证据", result_count=0)

        valid_results = [
            item
            for item in results
            if isinstance(item, dict) and len(str(item.get("content") or item.get("preview") or "")) >= self.min_content_length
        ]
        if not valid_results:
            return EvidenceDecision(False, "候选证据内容过短，不能支撑回答", result_count=len(results))

        scored = [(self._score(item), item) for item in valid_results]
        numeric_scores = [(score, item) for score, item in scored if score is not None]
        if numeric_scores:
            top_score, top_item = max(numeric_scores, key=lambda pair: pair[0])
            sufficient = top_score >= self.score_threshold
            reason = "知识库最高相关度达到阈值" if sufficient else "知识库最高相关度低于阈值"
            return EvidenceDecision(
                sufficient=sufficient,
                reason=reason,
                result_count=len(results),
                valid_count=len(valid_results),
                top_score=top_score,
                top_source=self._source_name(top_item),
            )

        sufficient = len(valid_results) >= 2
        reason = "存在多个有效候选证据" if sufficient else "有效候选证据不足"
        return EvidenceDecision(
            sufficient=sufficient,
            reason=reason,
            result_count=len(results),
            valid_count=len(valid_results),
            top_source=self._source_name(valid_results[0]),
        )

    def enough(self, results: Any) -> bool:
        return self.check(results).sufficient

    def _score(self, item: dict[str, Any]) -> float | None:
        value = item.get("rerank_score")
        metadata = item.get("metadata")
        if value in ("", None) and isinstance(metadata, dict):
            value = metadata.get("rerank_score")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _source_name(self, item: dict[str, Any]) -> str:
        return str(item.get("file_name") or item.get("source") or item.get("title") or "")
