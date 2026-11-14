from __future__ import annotations

import json
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm_client import build_llm
from backend.knowledge.knowledge_base import KnowledgeBase
from backend.knowledge.source_utils import format_agent_sources, parse_json_object
from backend.services.memory_store import ShortTermMemory
from backend.tools.web_search_tool import WebSearchTool


class ReactAgentService:
    def __init__(
        self,
        config: dict[str, str],
        knowledge_base: KnowledgeBase,
        memory: ShortTermMemory,
        web_search_tool: WebSearchTool | None = None,
    ) -> None:
        self.config = config
        self.knowledge_base = knowledge_base
        self.memory = memory
        self.web_search_tool = web_search_tool or WebSearchTool()

    def _ensure_api_key(self) -> None:
        if not self.config["api_key"]:
            raise RuntimeError("DeepSeek API key is not configured.")

    def _add_sources(
        self,
        target: list[dict[str, Any]],
        results: list[dict[str, Any]],
        tool: str,
        query: str,
    ) -> list[dict[str, Any]]:
        existing_keys = {
            source.get("url") or f"{source.get('source')}::{source.get('preview')}"
            for source in target
        }
        added: list[dict[str, Any]] = []
        for result in results:
            key = result.get("url") or f"{result.get('source')}::{result.get('preview')}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            source = dict(result)
            source["index"] = len(target) + 1
            source["tool"] = tool
            source["query"] = query
            target.append(source)
            added.append(source)
        return added

    def _choose_action(
        self,
        question: str,
        sources: list[dict[str, Any]],
        history: str,
        step: int,
        max_steps: int,
    ) -> dict[str, str]:
        llm = build_llm(self.config, reasoning=False, timeout=60)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你是一个 ReAct Agent 的工具决策器，只决定下一步动作，不直接回答用户。"
                        "可用动作：local_search=检索本地知识库；web_search=实时联网搜索；finish=资料足够，进入最终回答。"
                        "规则：至少使用一次工具；涉及最新、今天、价格、新闻、政策、实时信息时优先 web_search；"
                        "涉及企业制度、产品手册、运维流程、XX-200、客户数据、差旅报销、生产发布、故障应急、新员工入职、客服平台运营时优先 local_search；本地资料不足时可以再 web_search。"
                        "只输出 JSON 对象，不要输出 Markdown，不要输出完整思考过程。"
                        '格式：{"action":"local_search|web_search|finish","query":"搜索关键词","reason":"一句话说明"}'
                    )
                ),
                HumanMessage(
                    content=(
                        f"今天是 {date.today().isoformat()}。\n"
                        f"{history}\n\n"
                        f"用户问题：{question}\n"
                        f"当前步骤：{step}/{max_steps}\n"
                        f"已观察到的资料：\n{format_agent_sources(sources, limit=360)}"
                    )
                ),
            ]
        )
        decision = parse_json_object(str(response.content))
        action = str(decision.get("action") or "").strip()
        if action not in {"local_search", "web_search", "finish"}:
            action = "local_search" if not sources else "finish"
        if action == "finish" and not sources:
            action = "local_search"
        query = str(decision.get("query") or question).strip() or question
        reason = str(decision.get("reason") or "").strip()
        return {"action": action, "query": query, "reason": reason}

    def chat(
        self,
        question: str,
        top_k: int = 4,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        max_steps: int = 3,
    ) -> dict[str, Any]:
        self._ensure_api_key()

        history = self.memory.format_history(session_id, context_window) if use_memory else ""
        sources: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []

        for step in range(1, max_steps + 1):
            decision = self._choose_action(question, sources, history, step, max_steps)
            action = decision["action"]
            query = decision["query"]

            if action == "finish":
                trace.append(
                    {
                        "step": step,
                        "action": action,
                        "query": "",
                        "reason": decision.get("reason") or "已有资料，进入最终回答。",
                        "summary": f"累计 {len(sources)} 条资料。",
                    }
                )
                break

            tool_result: dict[str, Any] | None = None
            if action == "web_search":
                tool_result = self.web_search_tool.run_with_trace(query, max_results=top_k, fetch_pages=False)
                results = tool_result["results"]
            else:
                results = self.knowledge_base.search(query, top_k=top_k)

            added = self._add_sources(sources, results, action, query)
            summary = f"找到 {len(results)} 条，新增 {len(added)} 条。"
            if tool_result:
                summary = (
                    f"{tool_result.get('provider')} {tool_result.get('status')}，"
                    f"找到 {len(results)} 条，新增 {len(added)} 条，用时 {tool_result.get('duration_ms')}ms。"
                )
            trace.append(
                {
                    "step": step,
                    "action": action,
                    "query": query,
                    "reason": decision.get("reason") or "",
                    "summary": summary,
                    "provider": tool_result.get("provider") if tool_result else "",
                    "fallback_from": tool_result.get("fallback_from") if tool_result else "",
                    "result_count": tool_result.get("result_count") if tool_result else len(results),
                    "duration_ms": tool_result.get("duration_ms") if tool_result else "",
                    "retry_count": tool_result.get("retry_count") if tool_result else 0,
                    "status": tool_result.get("status") if tool_result else "",
                    "errors": tool_result.get("errors") if tool_result else [],
                }
            )

        llm = build_llm(self.config, reasoning=reasoning, timeout=150 if reasoning else 120)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你是一个严谨的 ReAct 问答助手。"
                        "请只根据工具检索得到的资料回答，并在关键结论后用 [编号] 标注来源。"
                        "不要输出完整思考过程；如果资料不足或来源互相矛盾，请明确说明。"
                        "历史对话只用于理解代词、上下文和用户意图，不能当作事实来源。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"{history}\n\n"
                        f"问题：{question}\n\n"
                        f"工具执行记录：\n{json.dumps(trace, ensure_ascii=False)}\n\n"
                        f"资料：\n{format_agent_sources(sources)}"
                    )
                ),
            ]
        )
        answer = str(response.content)
        if use_memory:
            self.memory.add_turn(session_id, question, answer, "agent")
        return {
            "question": question,
            "answer": answer,
            "model": self.config["model"],
            "mode": "react",
            "reasoning": reasoning,
            "reasoning_effort": "high" if reasoning else "off",
            "session_id": session_id,
            "use_memory": use_memory,
            "context_window": context_window,
            "memory_turns": self.memory.count(session_id),
            "trace": trace,
            "sources": sources,
        }
