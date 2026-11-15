from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.chat.modes import ChatQueryMode, ExecutionMode, parse_chat_query_mode
from backend.services.routing.answer_route_service import (
    CLARIFY,
    DIRECT_LLM,
    KB_ONLY,
    KB_THEN_WEB,
    NO_EVIDENCE,
    WEB_ONLY,
    AnswerRouteService,
)


@dataclass(frozen=True)
class ChatExecutionPlan:
    query_mode: ChatQueryMode
    execution_mode: ExecutionMode
    reason: str


class ChatOrchestrator:
    """Maps user-facing chat modes to backend execution modes."""

    def __init__(self, qa_service: Any, agent_service: Any, route_service: AnswerRouteService | None = None) -> None:
        self.qa_service = qa_service
        self.agent_service = agent_service
        self.route_service = route_service or AnswerRouteService()

    def plan(
        self,
        query_mode: str | ChatQueryMode | None,
        document_id: str = "",
        file_name: str = "",
    ) -> ChatExecutionPlan:
        mode = parse_chat_query_mode(query_mode)
        if mode == ChatQueryMode.OPEN_CHAT:
            return ChatExecutionPlan(mode, ExecutionMode.REACT_AGENT, "open chat uses lightweight answer routing")
        if mode == ChatQueryMode.DOCUMENT and not (document_id or file_name):
            return ChatExecutionPlan(mode, ExecutionMode.CLARIFICATION, "document mode requires a selected document")
        return ChatExecutionPlan(mode, ExecutionMode.RETRIEVAL, "knowledge-base retrieval answer")

    def chat(
        self,
        question: str,
        top_k: int = 4,
        query_mode: str | ChatQueryMode | None = ChatQueryMode.AUTO_DOCUMENT,
        retrieval_mode: str = "hybrid_rerank",
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        document_id: str = "",
        file_name: str = "",
    ) -> dict[str, Any]:
        plan = self.plan(query_mode, document_id=document_id, file_name=file_name)

        if plan.execution_mode == ExecutionMode.CLARIFICATION:
            result = self._clarification_response(question, plan, session_id, use_memory, context_window)
        elif plan.query_mode == ChatQueryMode.OPEN_CHAT:
            result = self.open_chat(
                question,
                top_k,
                reasoning,
                session_id,
                use_memory,
                context_window,
            )
        else:
            selected_file = file_name or document_id
            result = self.qa_service.chat(
                question,
                top_k,
                retrieval_mode,
                reasoning,
                session_id,
                use_memory,
                context_window,
                selected_file if plan.query_mode == ChatQueryMode.DOCUMENT else "",
            )
            route_info = self.route_service.route_question(question, plan.query_mode.value)
            self._decorate_route(result, route_info)

        result["query_mode"] = plan.query_mode.value
        result["execution_mode"] = plan.execution_mode.value
        result["execution_reason"] = plan.reason
        if document_id:
            result["document_id"] = document_id
        if file_name:
            result["file_name"] = file_name
        return result

    def open_chat(
        self,
        question: str,
        top_k: int = 4,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
    ) -> dict[str, Any]:
        if self._is_search_provider_question(question):
            return self._search_provider_response(question, session_id, use_memory, context_window)

        route_info = self.route_service.route_question(question, ChatQueryMode.OPEN_CHAT.value)
        route = route_info["route"]

        if route == WEB_ONLY:
            trace = [self._trace_item(1, "web_search", question, "开放提问路由到联网搜索")]
            try:
                result = self.qa_service.web_chat(question, top_k, reasoning, session_id, use_memory, context_window)
            except RuntimeError:
                return self._no_evidence_response(question, route_info, session_id, use_memory, context_window, trace)
            self._decorate_route(result, route_info, trace)
            return result

        if route == CLARIFY:
            return self._clarify_question_response(question, route_info, session_id, use_memory, context_window)

        result = self.qa_service.direct_chat(question, reasoning, session_id, use_memory, context_window)
        self._decorate_route(result, route_info)
        return result

    def auto_chat(
        self,
        question: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid_rerank",
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
    ) -> dict[str, Any]:
        if self._is_search_provider_question(question):
            return self._search_provider_response(question, session_id, use_memory, context_window)

        early_route = self.route_service.route_question(question, "AUTO_MODE", kb_results=None)
        if early_route["route"] == DIRECT_LLM:
            result = self.qa_service.direct_chat(question, reasoning, session_id, use_memory, context_window)
            self._decorate_route(result, early_route)
            return result

        if early_route["route"] == WEB_ONLY:
            trace = [self._trace_item(1, "web_search", question, early_route["route_reason"])]
            try:
                result = self.qa_service.web_chat(question, top_k, reasoning, session_id, use_memory, context_window)
            except RuntimeError:
                return self._no_evidence_response(question, early_route, session_id, use_memory, context_window, trace)
            self._decorate_route(result, early_route, trace)
            return result

        if early_route["route"] == CLARIFY:
            return self._clarify_question_response(question, early_route, session_id, use_memory, context_window)

        trace: list[dict[str, Any]] = []
        kb_results = self.qa_service.retrieve_sources(question, top_k, retrieval_mode)
        trace.append(self._trace_item(1, "local_search", question, f"找到 {len(kb_results)} 条知识库候选证据"))
        route_info = self.route_service.route_question(question, "AUTO_MODE", kb_results=kb_results)
        route = route_info["route"]

        if route == KB_ONLY:
            result = self.qa_service.chat(
                question,
                top_k,
                retrieval_mode,
                reasoning,
                session_id,
                use_memory,
                context_window,
                precomputed_sources=kb_results,
            )
            self._decorate_route(result, route_info, trace)
            return result

        if route == DIRECT_LLM:
            result = self.qa_service.direct_chat(question, reasoning, session_id, use_memory, context_window)
            self._decorate_route(result, route_info, trace)
            return result

        if route == WEB_ONLY:
            trace.append(self._trace_item(2, "web_search", question, route_info["route_reason"]))
            try:
                result = self.qa_service.web_chat(question, top_k, reasoning, session_id, use_memory, context_window)
            except RuntimeError:
                return self._no_evidence_response(question, route_info, session_id, use_memory, context_window, trace)
            self._decorate_route(result, route_info, trace)
            return result

        if route == KB_THEN_WEB:
            trace.append(self._trace_item(2, "web_search", question, "知识库证据不足，执行联网补充"))
            try:
                result = self.qa_service.web_chat(
                    question,
                    top_k,
                    reasoning,
                    session_id,
                    use_memory,
                    context_window,
                    answer_prefix="知识库未检索到足够证据，以下基于联网搜索结果回答。",
                )
            except RuntimeError:
                no_evidence = dict(route_info)
                no_evidence["route"] = NO_EVIDENCE
                no_evidence["route_reason"] = "知识库和联网搜索都没有找到可用证据"
                return self._no_evidence_response(question, no_evidence, session_id, use_memory, context_window, trace)
            self._decorate_route(result, route_info, trace)
            return result

        if route == CLARIFY:
            return self._clarify_question_response(question, route_info, session_id, use_memory, context_window, trace)

        return self._no_evidence_response(question, route_info, session_id, use_memory, context_window, trace)

    def _clarification_response(
        self,
        question: str,
        plan: ChatExecutionPlan,
        session_id: str,
        use_memory: bool,
        context_window: int,
    ) -> dict[str, Any]:
        return {
            "question": question,
            "answer": "当前文档问答需要先选择一份文档。请先在文档列表中选中文档，再继续提问。",
            "model": "",
            "reasoning": False,
            "reasoning_effort": "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": 0,
            "sources": [],
            "query_mode": plan.query_mode.value,
            "execution_mode": plan.execution_mode.value,
            "execution_reason": plan.reason,
            "route": KB_ONLY,
            "route_reason": "当前文档问答需要先选择文档，未进入联网搜索",
            "tool_traces": [],
            "answer_source": "知识库",
        }

    def _decorate_route(
        self,
        result: dict[str, Any],
        route_info: dict[str, Any],
        tool_traces: list[dict[str, Any]] | None = None,
    ) -> None:
        traces = list(tool_traces if tool_traces is not None else route_info.get("tool_traces", []))
        web_trace = result.get("web_search_trace")
        if isinstance(web_trace, dict):
            web_trace_item = self._web_trace_item(len(traces) + 1, web_trace)
            if traces and traces[-1].get("action") == "web_search" and not traces[-1].get("provider"):
                original_summary = traces[-1].get("summary") or traces[-1].get("reason") or ""
                web_trace_item["step"] = traces[-1].get("step", web_trace_item["step"])
                if original_summary:
                    web_trace_item["reason"] = original_summary
                    web_trace_item["summary"] = f"{original_summary}；{web_trace_item['summary']}"
                traces[-1] = web_trace_item
            else:
                traces.append(web_trace_item)
        result["route"] = route_info.get("route", "")
        result["route_reason"] = route_info.get("route_reason", "")
        result["route_confidence"] = route_info.get("route_confidence", "")
        result["route_router"] = route_info.get("route_router", "")
        result["route_features"] = route_info.get("route_features", {})
        result["route_evidence"] = route_info.get("route_evidence", {})
        result["tool_traces"] = traces
        result["trace"] = traces
        result["answer_source"] = self._answer_source(str(result["route"]))

    def _clarify_question_response(
        self,
        question: str,
        route_info: dict[str, Any],
        session_id: str,
        use_memory: bool,
        context_window: int,
        tool_traces: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        answer = "这个问题指代不够明确，请补充你想问的是哪份文档、哪个流程或哪个对象。"
        if use_memory:
            self.qa_service.memory.add_turn(session_id, question, answer, "clarify")
        result = {
            "question": question,
            "answer": answer,
            "model": "",
            "reasoning": False,
            "reasoning_effort": "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.qa_service.memory.count(session_id),
            "sources": [],
        }
        self._decorate_route(result, route_info, tool_traces)
        return result

    def _trace_item(self, step: int, action: str, query: str, summary: str) -> dict[str, Any]:
        return {
            "step": step,
            "action": action,
            "query": query,
            "reason": summary,
            "summary": summary,
        }

    def _web_trace_item(self, step: int, tool_result: dict[str, Any]) -> dict[str, Any]:
        provider = tool_result.get("provider") or "unknown"
        status = tool_result.get("status") or "unknown"
        result_count = tool_result.get("result_count", 0)
        duration_ms = tool_result.get("duration_ms", 0)
        retry_count = tool_result.get("retry_count", 0)
        fallback_from = tool_result.get("fallback_from") or ""
        fallback_text = f"，由 {fallback_from} fallback" if fallback_from else ""
        retry_text = f"，重试 {retry_count} 次" if retry_count else ""
        summary = f"{provider} {status}{fallback_text}{retry_text}，返回 {result_count} 条，用时 {duration_ms}ms"
        errors = tool_result.get("errors") or []
        if errors:
            summary = f"{summary}；错误：{' | '.join(str(error) for error in errors[:2])}"
        return {
            "step": step,
            "action": "web_search",
            "query": tool_result.get("query") or "",
            "reason": summary,
            "summary": summary,
            "provider": provider,
            "fallback_from": fallback_from,
            "result_count": result_count,
            "duration_ms": duration_ms,
            "retry_count": retry_count,
            "status": status,
            "errors": errors,
        }

    def _no_evidence_response(
        self,
        question: str,
        route_info: dict[str, Any],
        session_id: str,
        use_memory: bool,
        context_window: int,
        tool_traces: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        answer = "没有在知识库或联网搜索中找到足够证据，暂时无法给出可靠回答。"
        if use_memory:
            self.qa_service.memory.add_turn(session_id, question, answer, "no_evidence")
        result = {
            "question": question,
            "answer": answer,
            "model": "",
            "reasoning": False,
            "reasoning_effort": "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.qa_service.memory.count(session_id),
            "sources": [],
        }
        self._decorate_route(result, route_info, tool_traces)
        return result

    def _is_search_provider_question(self, question: str) -> bool:
        text = str(question or "").strip().lower()
        if not text:
            return False
        web_markers = ("联网", "上网", "网页", "web", "搜索")
        provider_markers = (
            "用的什么",
            "用什么",
            "什么搜索",
            "搜索源",
            "搜索服务",
            "搜索工具",
            "搜索引擎",
            "provider",
            "tavily",
            "google",
            "duckduckgo",
        )
        return any(marker in text for marker in web_markers) and any(
            marker in text for marker in provider_markers
        )

    def _search_provider_response(
        self,
        question: str,
        session_id: str,
        use_memory: bool,
        context_window: int,
    ) -> dict[str, Any]:
        web_info = self.qa_service.web_search_tool.info()
        provider = web_info.get("provider") or "unknown"
        fallback = web_info.get("fallback") or "none"
        retries = web_info.get("tavily_max_retries", 0)
        tavily_configured = "已配置" if web_info.get("tavily_configured") else "未配置"
        chain = web_info.get("provider_chain") or f"{provider} -> {fallback}"
        answer = (
            f"当前联网搜索主工具是 {provider}，Tavily 状态：{tavily_configured}。"
            f"搜索链路是：{chain}。"
            f"如果 Tavily 临时失败，会最多重试 {retries} 次；仍失败时默认 fallback 到 {fallback}。"
            "刚才回答里出现“Google 搜索”不是实际工具配置，而是模型在回答系统能力问题时的误判。"
        )
        if use_memory:
            self.qa_service.memory.add_turn(session_id, question, answer, "system_info")
        result = {
            "question": question,
            "answer": answer,
            "model": "",
            "reasoning": False,
            "reasoning_effort": "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.qa_service.memory.count(session_id),
            "sources": [],
        }
        route_info = {
            "route": DIRECT_LLM,
            "route_reason": "用户询问系统联网搜索工具，直接读取 WebSearchTool 配置，不调用联网搜索",
            "route_confidence": 1.0,
            "route_router": "system_info_guard",
            "route_features": {},
            "route_evidence": {},
            "tool_traces": [
                {
                    "step": 1,
                    "action": "system_info",
                    "query": question,
                    "reason": f"读取当前 WebSearchTool 配置：provider={provider}",
                    "summary": f"provider={provider}, fallback={fallback}, tavily_configured={tavily_configured}",
                    "provider": provider,
                    "fallback_from": "",
                    "result_count": 0,
                    "duration_ms": 0,
                    "retry_count": 0,
                    "status": "success",
                    "errors": [],
                }
            ],
        }
        self._decorate_route(result, route_info)
        return result

    def _answer_source(self, route: str) -> str:
        if route == KB_ONLY:
            return "知识库"
        if route == WEB_ONLY:
            return "联网搜索"
        if route == KB_THEN_WEB:
            return "知识库不足，已联网补充"
        if route == DIRECT_LLM:
            return "普通回答"
        if route == CLARIFY:
            return "需要澄清"
        if route == NO_EVIDENCE:
            return "无可用证据"
        return "未分类"
