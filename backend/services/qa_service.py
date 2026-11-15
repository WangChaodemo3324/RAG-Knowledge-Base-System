from __future__ import annotations

import logging
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm_client import build_llm
from backend.knowledge.knowledge_base import KnowledgeBase
from backend.knowledge.source_utils import source_content
from backend.services.memory_store import ShortTermMemory
from backend.tools.web_search_tool import WebSearchTool

logger = logging.getLogger(__name__)


class QAService:
    def __init__(
        self,
        config: dict[str, str],
        knowledge_base: KnowledgeBase,
        memory: ShortTermMemory,
        hybrid_search: Any | None = None,
        rerank: Any | None = None,
        web_search_tool: WebSearchTool | None = None,
    ) -> None:
        self.config = config
        self.knowledge_base = knowledge_base
        self.memory = memory
        self.hybrid_search = hybrid_search
        self.rerank = rerank
        self.web_search_tool = web_search_tool or WebSearchTool()

    def _ensure_api_key(self) -> None:
        if not self.config["api_key"]:
            raise RuntimeError("DeepSeek API key is not configured.")

    def _retrieve_sources(
        self,
        search_query: str,
        top_k: int,
        retrieval_mode: str,
        file_name: str = "",
    ) -> list[dict[str, Any]]:
        mode = (retrieval_mode or "hybrid_rerank").strip().lower()
        if mode == "vector":
            return self.knowledge_base.search(search_query, top_k=top_k, file_name=file_name)
        if mode == "hybrid_rerank":
            return self._hybrid_rerank_sources(search_query, top_k, file_name=file_name)
        raise RuntimeError(f"Unsupported retrieval_mode: {retrieval_mode}")

    def retrieve_sources(
        self,
        search_query: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid_rerank",
        file_name: str = "",
    ) -> list[dict[str, Any]]:
        return self._retrieve_sources(search_query, top_k, retrieval_mode, file_name=file_name)

    def _hybrid_rerank_sources(self, search_query: str, top_k: int, file_name: str = "") -> list[dict[str, Any]]:
        if self.hybrid_search is None or self.rerank is None:
            raise RuntimeError("Hybrid rerank retrieval is not configured.")

        hybrid_top_k = max(top_k * 3, 10)
        rerank_top_k = max(top_k * 2, 5)
        candidates = self.hybrid_search.search(
            search_query,
            top_k=hybrid_top_k,
            vector_top_k=max(hybrid_top_k, 10),
            keyword_top_k=max(hybrid_top_k, 10),
            rrf_k=60,
            file_name=file_name,
        )
        reranked_children = self.rerank.rerank(search_query, candidates, top_k=rerank_top_k)
        return self.knowledge_base.expand_child_candidates(reranked_children, top_k=top_k)

    def chat(
        self,
        question: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid_rerank",
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        file_name: str = "",
        precomputed_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._ensure_api_key()

        history = self.memory.format_history(session_id, context_window) if use_memory else ""
        search_query = f"{history}\n当前问题：{question}" if history else question
        if precomputed_sources is not None:
            # orchestrator already retrieved (evidence check) — reuse instead of
            # running embedding + RRF + rerank a second time
            sources = precomputed_sources
        else:
            sources = self._retrieve_sources(
                search_query,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
                file_name=file_name,
            )
        context = "\n\n".join(f"[{source['index']}] {source['content']}" for source in sources)
        llm = build_llm(self.config, reasoning=reasoning, timeout=90 if reasoning else 60)
        reasoning_instruction = (
            "请先在内部检查资料是否足以支持结论，不要输出思考过程；最终答案要明确结论、依据和资料不足处。"
            if reasoning
            else ""
        )
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你是一个严谨的知识库问答助手。"
                        "请只根据给定资料回答，并在关键结论后用 [编号] 标注来源；如果资料不足，请明确说明资料中没有找到答案。"
                        "历史对话只用于理解代词、上下文和用户意图，不能当作事实来源。"
                        f"{reasoning_instruction}"
                    )
                ),
                HumanMessage(content=f"{history}\n\n资料：\n{context}\n\n当前问题：{question}"),
            ]
        )
        answer = str(response.content)
        if use_memory:
            self.memory.add_turn(session_id, question, answer, "chat")
        return {
            "question": question,
            "answer": answer,
            "model": self.config["model"],
            "retrieval_mode": retrieval_mode,
            "file_name": file_name,
            "reasoning": reasoning,
            "reasoning_effort": "high" if reasoning else "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.memory.count(session_id),
            "sources": sources,
        }

    def chat_stream(
        self,
        question: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid_rerank",
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        file_name: str = "",
        precomputed_sources: list[dict[str, Any]] | None = None,
    ):
        """SSE-ready generator for knowledge-base chat.

        Yields dicts: {"type": "sources"|"token"|"done"|"error", ...}.
        Memory is written in a finally block so client disconnects (GeneratorExit)
        still record the partial answer — no background task leakage.
        """
        self._ensure_api_key()

        history = self.memory.format_history(session_id, context_window) if use_memory else ""
        search_query = f"{history}\n当前问题：{question}" if history else question
        if precomputed_sources is not None:
            sources = precomputed_sources
        else:
            sources = self._retrieve_sources(
                search_query,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
                file_name=file_name,
            )
        context = "\n\n".join(f"[{source['index']}] {source['content']}" for source in sources)
        llm = build_llm(self.config, reasoning=reasoning, timeout=90 if reasoning else 60)
        reasoning_instruction = (
            "请先在内部检查资料是否足以支持结论，不要输出思考过程；最终答案要明确结论、依据和资料不足处。"
            if reasoning
            else ""
        )

        yield {"type": "sources", "sources": sources, "model": self.config["model"], "file_name": file_name}

        collected: list[str] = []
        completed = False
        client_closed = False
        error_detail = ""
        try:
            response = llm.stream(
                [
                    SystemMessage(
                        content=(
                            "你是一个严谨的知识库问答助手。"
                            "请只根据给定资料回答，并在关键结论后用 [编号] 标注来源；如果资料不足，请明确说明资料中没有找到答案。"
                            "历史对话只用于理解代词、上下文和用户意图，不能当作事实来源。"
                            f"{reasoning_instruction}"
                        )
                    ),
                    HumanMessage(content=f"{history}\n\n资料：\n{context}\n\n当前问题：{question}"),
                ]
            )
            for chunk in response:
                token = str(chunk.content or "")
                if token:
                    collected.append(token)
                    yield {"type": "token", "text": token}
            completed = True
        except GeneratorExit:
            # client disconnected — record partial answer in finally, do NOT yield
            client_closed = True
            raise
        except Exception as exc:
            logger.warning("chat_stream generation failed: %s", exc)
            error_detail = "模型生成中断，请稍后重试"
        finally:
            answer = "".join(collected)
            if not completed and answer:
                answer += "\n\n（连接中断，以上为已生成的部分内容）"
            if use_memory and answer:
                self.memory.add_turn(session_id, question, answer, "chat" if completed else "chat_interrupted")
            if not client_closed:
                if error_detail:
                    yield {"type": "error", "detail": error_detail}
                yield {
                    "type": "done",
                    "completed": completed,
                    "answer": answer,
                    "memory_turns": self.memory.count(session_id),
                    "sources_count": len(sources),
                }

    def web_search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        return self.web_search_tool.run(query, max_results=top_k, fetch_pages=False)

    def web_search_with_trace(self, query: str, top_k: int = 4) -> dict[str, Any]:
        return self.web_search_tool.run_with_trace(query, max_results=top_k, fetch_pages=False)

    def direct_chat(
        self,
        question: str,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
    ) -> dict[str, Any]:
        self._ensure_api_key()

        history = self.memory.format_history(session_id, context_window) if use_memory else ""
        llm = build_llm(self.config, reasoning=reasoning, timeout=90 if reasoning else 60)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        f"今天是 {date.today().isoformat()}。"
                        "你是一个通用问答助手。当前回答不强制使用本地知识库或联网搜索。"
                        "如果问题涉及实时信息、价格、天气、新闻、最新版本等，请提醒用户需要联网资料才能确认。"
                        "历史对话只用于理解代词、上下文和用户意图。"
                    )
                ),
                HumanMessage(content=f"{history}\n\n当前问题：{question}"),
            ]
        )
        answer = str(response.content)
        if use_memory:
            self.memory.add_turn(session_id, question, answer, "direct")
        return {
            "question": question,
            "answer": answer,
            "model": self.config["model"],
            "reasoning": reasoning,
            "reasoning_effort": "high" if reasoning else "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.memory.count(session_id),
            "sources": [],
        }

    def web_chat(
        self,
        question: str,
        top_k: int = 4,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        answer_prefix: str = "",
    ) -> dict[str, Any]:
        self._ensure_api_key()

        history = self.memory.format_history(session_id, context_window) if use_memory else ""
        query_context = self.memory.query_context(session_id, context_window) if use_memory else ""
        search_query = f"{query_context} {question}".strip() or question
        tool_result = self.web_search_tool.run_with_trace(search_query, max_results=top_k, fetch_pages=False)
        sources = tool_result["results"]
        if not sources:
            raise RuntimeError("Web search returned no results.")

        context = "\n\n".join(
            (
                f"[{source['index']}] {source.get('title') or source.get('source')}\n"
                f"URL: {source.get('url')}\n"
                f"内容: {source_content(source)}"
            )
            for source in sources
        )
        llm = build_llm(self.config, reasoning=reasoning, timeout=120 if reasoning else 90)
        reasoning_instruction = (
            "请先在内部比较不同来源，检查时间、主体和结论是否一致，不要输出思考过程；最终答案要说清楚确定结论和不确定处。"
            if reasoning
            else ""
        )
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        f"今天是 {date.today().isoformat()}。"
                        "你是一个严谨的联网资料问答助手。"
                        "请仅根据提供的联网搜索资料回答，并在关键结论后用 [编号] 标注来源。"
                        "不要编造没有出现在资料里的来源、时间、数据或结论。"
                        "如果资料不足或来源互相矛盾，请明确说明。"
                        "历史对话只用于理解代词、上下文和用户意图，不能当作事实来源。"
                        f"{reasoning_instruction}"
                    )
                ),
                HumanMessage(content=f"{history}\n\n网页资料：\n{context}\n\n当前问题：{question}"),
            ]
        )
        answer = str(response.content)
        if answer_prefix:
            answer = f"{answer_prefix}\n\n{answer}"
        if use_memory:
            self.memory.add_turn(session_id, question, answer, "web")
        return {
            "question": question,
            "answer": answer,
            "model": self.config["model"],
            "reasoning": reasoning,
            "reasoning_effort": "high" if reasoning else "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.memory.count(session_id),
            "sources": sources,
            "web_search_trace": {
                "tool": tool_result.get("tool"),
                "provider": tool_result.get("provider"),
                "fallback_from": tool_result.get("fallback_from"),
                "query": tool_result.get("query"),
                "result_count": tool_result.get("result_count"),
                "duration_ms": tool_result.get("duration_ms"),
                "retry_count": tool_result.get("retry_count", 0),
                "status": tool_result.get("status"),
                "errors": tool_result.get("errors", []),
            },
        }
