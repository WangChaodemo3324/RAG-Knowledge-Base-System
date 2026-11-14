from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.services.routing.evidence_checker import EvidenceChecker
from backend.services.routing.feature_extractor import QueryFeatureExtractor
from backend.services.routing.llm_router import LLMRouter
from backend.services.routing.route_schema import (
    CLARIFY,
    DIRECT_LLM,
    KB_ONLY,
    KB_THEN_WEB,
    NO_EVIDENCE,
    WEB_ONLY,
    EvidenceDecision,
    QueryFeatures,
    RouteDecision,
)
from backend.services.routing.route_trace_logger import RouteTraceLogger


class ModeGuard:
    DOCUMENT_MODES = {"DOCUMENT", "AUTO_DOCUMENT", "CHAT", "DOCUMENT_CHAT"}
    OPEN_MODES = {"OPEN_CHAT", "OPEN", "OPEN_QUESTION", "WEB", "WEB_CHAT"}
    AUTO_MODES = {"AUTO", "AUTO_MODE", "AGENT", "AGENT_CHAT"}

    def normalize(self, value: str) -> str:
        return str(value or "").strip().upper()

    def is_document(self, mode: str) -> bool:
        return self.normalize(mode) in self.DOCUMENT_MODES

    def is_open(self, mode: str) -> bool:
        return self.normalize(mode) in self.OPEN_MODES

    def is_auto(self, mode: str) -> bool:
        return self.normalize(mode) in self.AUTO_MODES


class AnswerRouteService:
    """Engineering router for KB, web, direct LLM, and clarification decisions."""

    def __init__(self, config: dict[str, str] | None = None) -> None:
        self.mode_guard = ModeGuard()
        self.feature_extractor = QueryFeatureExtractor()
        self.evidence_checker = EvidenceChecker()
        self.llm_router = LLMRouter(config)
        self.trace_logger = RouteTraceLogger()

    def user_explicit_web(self, query: str) -> bool:
        return self.feature_extractor.extract(query).explicit_web

    def time_sensitive(self, query: str) -> bool:
        return self.feature_extractor.extract(query).has_current_time_need

    def direct_llm_candidate(self, query: str) -> bool:
        features = self.feature_extractor.extract(query)
        return self._direct_candidate(features)

    def kb_candidate(self, query: str) -> bool:
        features = self.feature_extractor.extract(query)
        return features.has_company_domain_hint or features.has_file_context

    def evidence_enough(self, results: Any) -> bool:
        return self.evidence_checker.enough(results)

    def route_question(
        self,
        query: str,
        query_mode: str,
        kb_results: Any = None,
        document_id: str = "",
        file_name: str = "",
    ) -> dict[str, Any]:
        started_at = perf_counter()
        mode = self.mode_guard.normalize(query_mode)
        features = self.feature_extractor.extract(query, mode, document_id, file_name)
        evidence: EvidenceDecision | None = None

        if self.mode_guard.is_document(mode):
            decision = RouteDecision(
                KB_ONLY,
                "文档问答模式强制使用本地知识库，不调用联网搜索",
                router="mode_guard",
                features=features,
            )
            return self._finish(query, mode, decision, started_at, features, evidence)

        if self.mode_guard.is_open(mode):
            decision = self._route_open(query, features)
            return self._finish(query, mode, decision, started_at, features, evidence)

        if self.mode_guard.is_auto(mode):
            decision, evidence = self._route_auto(query, features, kb_results)
            return self._finish(query, mode, decision, started_at, features, evidence)

        decision = RouteDecision(
            DIRECT_LLM,
            f"未知 query_mode={query_mode}，按普通开放问题处理",
            confidence=0.5,
            router="mode_guard",
            features=features,
        )
        return self._finish(query, mode, decision, started_at, features, evidence)

    def _route_open(self, query: str, features: QueryFeatures) -> RouteDecision:
        if features.is_vague_reference:
            return RouteDecision(CLARIFY, "问题指代不清，需要用户补充对象", router="feature_guard", features=features)
        if features.explicit_web:
            return RouteDecision(WEB_ONLY, "用户明确要求联网搜索", router="mode_guard", features=features)
        if features.has_current_time_need:
            return RouteDecision(WEB_ONLY, "问题包含时效性信息，优先联网搜索", router="feature_guard", features=features)
        return RouteDecision(
            DIRECT_LLM,
            "开放式提问且无明确联网或时效需求，直接调用大模型回答",
            router="mode_guard",
            features=features,
        )

    def _route_auto(
        self,
        query: str,
        features: QueryFeatures,
        kb_results: Any,
    ) -> tuple[RouteDecision, EvidenceDecision | None]:
        if features.is_vague_reference:
            return (
                RouteDecision(CLARIFY, "问题指代不清，需要用户补充对象", router="feature_guard", features=features),
                None,
            )

        if self._direct_candidate(features):
            return (
                RouteDecision(
                    DIRECT_LLM,
                    "简单数学、闲聊、常识或语言处理问题，无需检索和联网",
                    router="feature_guard",
                    features=features,
                ),
                None,
            )

        if features.explicit_web:
            return (
                RouteDecision(WEB_ONLY, "用户明确要求联网搜索", router="feature_guard", features=features),
                None,
            )

        if features.has_company_domain_hint or features.has_file_context or features.has_private_internal_hint:
            return self._route_kb_candidate(query, features, kb_results)

        if features.has_current_time_need:
            return (
                RouteDecision(WEB_ONLY, "问题需要实时信息，优先联网搜索", router="feature_guard", features=features),
                None,
            )

        if kb_results is None:
            return (
                RouteDecision(
                    KB_ONLY,
                    "规则无法高置信判断，先检索本地知识库，再做证据判断",
                    confidence=0.62,
                    router="rule_router",
                    features=features,
                ),
                None,
            )

        evidence = self.evidence_checker.check(kb_results)
        if evidence.sufficient:
            return (
                RouteDecision(
                    KB_ONLY,
                    "知识库检索到足够证据",
                    router="evidence_checker",
                    features=features,
                    evidence=evidence,
                ),
                evidence,
            )

        llm_decision = self.llm_router.route(query, features)
        if llm_decision.route == WEB_ONLY:
            return (
                RouteDecision(
                    KB_THEN_WEB,
                    "知识库证据不足，LLM Router 判断需要联网补充",
                    confidence=llm_decision.confidence,
                    router=llm_decision.router,
                    features=features,
                    evidence=evidence,
                ),
                evidence,
            )
        if llm_decision.route == KB_ONLY:
            return (
                RouteDecision(
                    NO_EVIDENCE,
                    "LLM Router 判断应查知识库，但知识库证据不足",
                    confidence=llm_decision.confidence,
                    router=llm_decision.router,
                    features=features,
                    evidence=evidence,
                ),
                evidence,
            )
        return (
            RouteDecision(
                llm_decision.route,
                llm_decision.reason,
                confidence=llm_decision.confidence,
                router=llm_decision.router,
                features=features,
                evidence=evidence,
            ),
            evidence,
        )

    def _route_kb_candidate(
        self,
        query: str,
        features: QueryFeatures,
        kb_results: Any,
    ) -> tuple[RouteDecision, EvidenceDecision | None]:
        if kb_results is None:
            return (
                RouteDecision(KB_ONLY, "企业知识库相关问题，优先检索本地知识库", router="feature_guard", features=features),
                None,
            )

        evidence = self.evidence_checker.check(kb_results)
        if evidence.sufficient:
            return (
                RouteDecision(KB_ONLY, "命中知识库证据", router="evidence_checker", features=features, evidence=evidence),
                evidence,
            )

        if features.has_private_internal_hint:
            return (
                RouteDecision(
                    NO_EVIDENCE,
                    "像内部制度或私有业务问题，但知识库证据不足，不使用公网资料编造",
                    router="evidence_checker",
                    features=features,
                    evidence=evidence,
                ),
                evidence,
            )

        return (
            RouteDecision(
                KB_THEN_WEB,
                "看起来是业务知识问题，但知识库证据不足，降级到联网补充",
                router="evidence_checker",
                features=features,
                evidence=evidence,
            ),
            evidence,
        )

    def _direct_candidate(self, features: QueryFeatures) -> bool:
        if features.explicit_web or features.has_current_time_need:
            return False
        if features.has_company_domain_hint or features.has_file_context or features.has_private_internal_hint:
            return False
        return features.is_math_like or features.is_chat_like or features.is_instruction_task

    def _finish(
        self,
        query: str,
        mode: str,
        decision: RouteDecision,
        started_at: float,
        features: QueryFeatures,
        evidence: EvidenceDecision | None,
    ) -> dict[str, Any]:
        duration_ms = int((perf_counter() - started_at) * 1000)
        self.trace_logger.log(query, mode, decision, duration_ms, features, evidence)
        return decision.to_dict()
