from __future__ import annotations

from pydantic import BaseModel, Field

from backend.chat.modes import ChatQueryMode


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索问题")
    top_k: int = Field(4, ge=1, le=10, description="返回的相关片段数量")


class HybridSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索问题")
    top_k: int = Field(10, ge=1, le=30, description="RRF 后返回的 child 候选数量")
    vector_top_k: int = Field(10, ge=1, le=30, description="向量召回 child 数量")
    keyword_top_k: int = Field(10, ge=1, le=30, description="BM25 召回 child 数量")
    rrf_k: int = Field(60, ge=1, le=200, description="RRF 平滑参数")


class RerankSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索问题")
    top_k: int = Field(5, ge=1, le=10, description="rerank 后返回的 child 数量")
    vector_top_k: int = Field(10, ge=1, le=30, description="向量召回 child 数量")
    keyword_top_k: int = Field(10, ge=1, le=30, description="BM25 召回 child 数量")
    hybrid_top_k: int = Field(10, ge=1, le=30, description="RRF 粗排后送入 rerank 的 child 候选数量")
    rrf_k: int = Field(60, ge=1, le=200, description="RRF 平滑参数")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    top_k: int = Field(4, ge=1, le=10, description="提供给大模型的相关片段数量")
    query_mode: ChatQueryMode = Field(ChatQueryMode.AUTO_DOCUMENT, description="frontend chat query mode")
    retrieval_mode: str = Field("hybrid_rerank", description="chat retrieval mode: vector or hybrid_rerank")
    document_id: str = Field("", description="selected document id for DOCUMENT mode")
    file_name: str = Field("", description="selected file name for DOCUMENT mode")
    reasoning: bool = Field(False, description="是否启用 DeepSeek 推理模式")
    session_id: str = Field("default", min_length=1, max_length=80, description="短期记忆会话 ID")
    use_memory: bool = Field(True, description="是否读取并写入短期记忆")
    context_window: int = Field(4, ge=0, le=10, description="带入最近几轮历史对话")


class MemoryClearRequest(BaseModel):
    session_id: str = Field("default", min_length=1, max_length=80, description="要清空的短期记忆会话 ID")
