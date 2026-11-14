from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.chat.orchestrator import ChatOrchestrator
from backend.core.config import DATA_DIR, get_deepseek_config
from backend.knowledge.knowledge_base import KnowledgeBase
from backend.services.agent_service import ReactAgentService
from backend.services.document_service import save_uploaded_document
from backend.services.hybrid_search_service import HybridSearchService
from backend.services.keyword_search_service import KeywordSearchService
from backend.services.memory_store import ShortTermMemory
from backend.services.qa_service import QAService
from backend.services.rerank_service import RerankService
from backend.services.routing.answer_route_service import AnswerRouteService
from backend.tools.web_search_tool import WebSearchTool


class RagService:
    """Small facade used by FastAPI; implementation lives in focused modules."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.config = get_deepseek_config()
        self.memory = ShortTermMemory()
        self.knowledge_base = KnowledgeBase(data_dir)
        self.knowledge_base.ensure_bootstrapped()
        self.keyword_search_service = KeywordSearchService()
        self.hybrid_search_service = HybridSearchService(self.knowledge_base, self.keyword_search_service)
        self.rerank_service = RerankService()
        self.web_search_tool = WebSearchTool()
        self.answer_route_service = AnswerRouteService(self.config)
        self.qa = QAService(
            self.config,
            self.knowledge_base,
            self.memory,
            self.hybrid_search_service,
            self.rerank_service,
            self.web_search_tool,
        )
        self.agent = ReactAgentService(self.config, self.knowledge_base, self.memory, self.web_search_tool)
        self.chat_orchestrator = ChatOrchestrator(self.qa, self.agent, self.answer_route_service)
        # best-effort background warmup so the first rerank query is not cold
        threading.Thread(target=self._warmup_rerank, name="rerank-warmup", daemon=True).start()

    def _warmup_rerank(self) -> None:
        try:
            self.rerank_service._model()
        except Exception:  # noqa: BLE001 — warmup must never break startup
            pass

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        return self.knowledge_base.search(query, top_k)

    def keyword_search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        return self.keyword_search_service.search(query, top_k)

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        vector_top_k: int = 10,
        keyword_top_k: int = 10,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        return self.hybrid_search_service.search(query, top_k, vector_top_k, keyword_top_k, rrf_k)

    def rerank_search(
        self,
        query: str,
        top_k: int = 5,
        vector_top_k: int = 10,
        keyword_top_k: int = 10,
        hybrid_top_k: int = 10,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        candidates = self.hybrid_search(query, hybrid_top_k, vector_top_k, keyword_top_k, rrf_k)
        return self.rerank_service.rerank(query, candidates, top_k)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        question: str,
        top_k: int = 4,
        query_mode: str = "AUTO_DOCUMENT",
        retrieval_mode: str = "hybrid_rerank",
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
        document_id: str = "",
        file_name: str = "",
    ) -> dict[str, Any]:
        return self.chat_orchestrator.chat(
            question,
            top_k,
            query_mode,
            retrieval_mode,
            reasoning,
            session_id,
            use_memory,
            context_window,
            document_id,
            file_name,
        )

    def web_search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        return self.qa.web_search(query, top_k)

    def web_search_with_trace(self, query: str, top_k: int = 4) -> dict[str, Any]:
        return self.qa.web_search_with_trace(query, top_k)

    def web_chat(
        self,
        question: str,
        top_k: int = 4,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
    ) -> dict[str, Any]:
        return self.chat_orchestrator.open_chat(question, top_k, reasoning, session_id, use_memory, context_window)

    def react_chat(
        self,
        question: str,
        top_k: int = 4,
        reasoning: bool = False,
        session_id: str = "default",
        use_memory: bool = True,
        context_window: int = 4,
    ) -> dict[str, Any]:
        return self.chat_orchestrator.auto_chat(
            question,
            top_k,
            "hybrid_rerank",
            reasoning,
            session_id,
            use_memory,
            context_window,
        )

    def clear_memory(self, session_id: str = "default") -> dict[str, Any]:
        return self.memory.clear(session_id)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def upload_document(self, file: Any) -> dict[str, Any]:
        saved = await save_uploaded_document(file, self.knowledge_base.data_dir)
        result = self.knowledge_base.add_file(Path(saved["saved_to"]), replace_existing=saved["overwritten"])
        status = result.get("status", "indexed")
        skipped = status == "skipped"
        stats = result.get("total_stats") or {}
        message = (
            "上传成功，文件内容未变化，已跳过重复入库。"
            if skipped
            else "上传成功，已增量入库。新文档现在可以参与检索问答。"
        )
        return {
            **saved,
            "indexed": not skipped,
            "status": status,
            "index_mode": "active_version_swap",
            "indexed_document_count": result.get("total_stats", {}).get("document_count", 0),
            "indexed_parent_count": result.get("parent_count", 0),
            "indexed_chunk_count": result.get("chunk_count", 0),
            "total_document_count": stats.get("document_count", 0),
            "total_parent_count": stats.get("parent_count", 0),
            "total_chunk_count": stats.get("child_count", 0),
            "data_files": sorted((result.get("documents") or {}).keys()),
            "message": message,
        }

    def rebuild_knowledge_base(self) -> dict[str, Any]:
        result = self.knowledge_base.rebuild()
        stats = self.knowledge_base.info()
        return {
            **result,
            "status": "rebuilt",
            "document_count": stats.get("document_count", 0),
            "parent_count": stats.get("parent_count", 0),
            "chunk_count": stats.get("chunk_count", 0),
            "data_files": [item["file_name"] for item in result.get("indexed", [])],
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        info = self.knowledge_base.info()
        info.update(
            {
                "deepseek_model": self.config["model"],
                "deepseek_base_url": self.config["base_url"],
                "has_api_key": bool(self.config["api_key"]),
                "web_search": self.web_search_tool.info(),
                "memory": "in_memory_short_term",
                "keyword_search": self.keyword_search_service.info(),
                "rerank": self.rerank_service.info(),
            }
        )
        return info


@lru_cache(maxsize=1)
def get_rag_service() -> RagService:
    return RagService()
