from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm_client import build_llm
from backend.knowledge.source_utils import parse_json_object
from backend.services.routing.route_schema import CLARIFY, DIRECT_LLM, KB_ONLY, WEB_ONLY, QueryFeatures, RouteDecision


class LLMRouter:
    """Semantic fallback router used only when hard routing signals are uncertain."""

    ALLOWED_ROUTES = {DIRECT_LLM, KB_ONLY, WEB_ONLY, CLARIFY}

    def __init__(self, config: dict[str, str] | None = None, enabled: bool = True) -> None:
        self.config = config or {}
        self.enabled = enabled

    def route(self, query: str, features: QueryFeatures) -> RouteDecision:
        if not self.enabled or not self.config.get("api_key"):
            return self._fallback(query, features, "LLM Router 未启用或未配置 API Key")

        try:
            llm = build_llm(self.config, reasoning=False, timeout=30)
            response = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "你是企业问答系统的语义路由器，只负责选择回答来源，不回答用户问题。"
                            "可选 route：DIRECT_LLM=普通大模型回答；KB_ONLY=本地企业知识库；"
                            "WEB_ONLY=联网搜索；CLARIFY=问题指代不清，需要用户补充。"
                            "不要输出思考过程，只输出 JSON。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户问题：{query}\n"
                            f"问题特征：{features.to_dict()}\n\n"
                            "判断原则：\n"
                            "1. 简单数学、闲聊、翻译、润色、普通概念解释 -> DIRECT_LLM。\n"
                            "2. 企业制度、产品手册、流程规范、内部数据权限 -> KB_ONLY。\n"
                            "3. 今天、最新、新闻、价格、天气、官网网页等实时或公网问题 -> WEB_ONLY。\n"
                            "4. 只说“这个/那个/它”且没有明确对象 -> CLARIFY。\n\n"
                            '输出格式：{"route":"DIRECT_LLM|KB_ONLY|WEB_ONLY|CLARIFY","confidence":0.0,"reason":"一句话原因"}'
                        )
                    ),
                ]
            )
            parsed = parse_json_object(str(response.content))
            route = str(parsed.get("route") or "").strip().upper()
            if route not in self.ALLOWED_ROUTES:
                return self._fallback(query, features, f"LLM Router 返回非法 route={route}")
            confidence = self._confidence(parsed.get("confidence"))
            reason = str(parsed.get("reason") or "LLM Router 语义判断").strip()
            return RouteDecision(route, reason, confidence=confidence, router="llm_router", features=features)
        except Exception as exc:
            return self._fallback(query, features, f"LLM Router 调用失败：{exc}")

    def _fallback(self, query: str, features: QueryFeatures, reason: str) -> RouteDecision:
        if features.is_vague_reference:
            return RouteDecision(CLARIFY, reason, confidence=0.55, router="llm_router_fallback", features=features)
        if features.explicit_web or features.has_current_time_need:
            return RouteDecision(WEB_ONLY, reason, confidence=0.65, router="llm_router_fallback", features=features)
        if features.has_company_domain_hint or features.has_private_internal_hint or features.has_file_context:
            return RouteDecision(KB_ONLY, reason, confidence=0.65, router="llm_router_fallback", features=features)
        return RouteDecision(DIRECT_LLM, reason, confidence=0.55, router="llm_router_fallback", features=features)

    def _confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.7
        return max(0.0, min(1.0, confidence))
