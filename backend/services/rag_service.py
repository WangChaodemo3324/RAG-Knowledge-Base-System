from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.chat.orchestrator import ChatOrchestrator
from backend.core.config import DATA_DIR, get_deepseek_config
from backend.knowledge.knowledge_base import KnowledgeBase
from backend.services.agent_service import ReactAgentService
from backend.services.routing.answer_route_service import AnswerRouteService
from backend.services.document_service import save_uploaded_document
from backend.services.hybrid_search_service import HybridSearchService
from backend.services.keyword_search_service import KeywordSearchService
from backend.services.memory_store import ShortTermMemory
from backend.services.qa_service import QAService
from backend.services.rerank_service import RerankService
from backend.tools.web_search_tool import WebSearchTool


class RagService:
    """Small facade used by FastAPI; implementation lives in focused modules."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.config = get_deepseek_config()
        self.memory = ShortTermMemory()
        self._bind_knowledge_base(KnowledgeBase(data_dir))

    def _bind_knowledge_base(self, knowledge_base: KnowledgeBase) -> None:
        self.knowledge_base = knowledge_base
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

    async def upload_document(self, file: Any) -> dict[str, Any]:
        saved = await save_uploaded_document(file, self.knowledge_base.data_dir)
        indexed = self.knowledge_base.add_file(Path(saved["saved_to"]), replace_existing=saved["overwritten"])
        status = indexed.get("status")
        message = (
            "上传成功，文件内容未变化，已跳过重复入库。"
            if status == "skipped"
            else "上传成功，已增量入库。新文档现在可以参与检索问答。"
        )
        return {
            **saved,
            "indexed": status == "indexed",
            "status": status,
            "index_mode": indexed["index_mode"],
            "indexed_document_count": indexed["document_count"],
            "indexed_parent_count": indexed["parent_count"],
            "indexed_chunk_count": indexed["chunk_count"],
            "total_document_count": indexed["total_document_count"],
            "total_parent_count": indexed["total_parent_count"],
            "total_chunk_count": indexed["total_chunk_count"],
            "data_files": indexed["data_files"],
            "message": message,
        }

    def rebuild_knowledge_base(self) -> dict[str, Any]:
        return self.knowledge_base.rebuild()

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
