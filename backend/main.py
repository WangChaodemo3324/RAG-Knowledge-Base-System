from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.schemas import ChatRequest, HybridSearchRequest, MemoryClearRequest, RerankSearchRequest, SearchRequest
from backend.services.document_service import DocumentUploadError
from backend.services.rag_service import get_rag_service


app = FastAPI(title="LangChain RAG API", version="1.0.0")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
WEB_DIR = PROJECT_ROOT / "web"
WEB_INDEX = FRONTEND_DIR / "index.html"
WEB_STANDALONE_INDEX = WEB_DIR / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/src", StaticFiles(directory=FRONTEND_DIR / "src"), name="frontend-src")
app.mount("/web-src", StaticFiles(directory=WEB_DIR / "src"), name="web-src")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    response = FileResponse(WEB_INDEX)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/web", include_in_schema=False)
@app.get("/web/", include_in_schema=False)
def web_root() -> FileResponse:
    response = FileResponse(WEB_STANDALONE_INDEX)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "LangChain RAG API",
        "docs": "/docs",
        "endpoints": [
            "/info",
            "/documents/upload",
            "/knowledge-base/rebuild",
            "/search",
            "/keyword-search",
            "/hybrid-search",
            "/rerank-search",
            "/chat",
            "/web-search",
            "/web-chat",
            "/agent-chat",
            "/memory/clear",
        ],
    }


@app.get("/info")
def info() -> dict[str, Any]:
    service = get_rag_service()
    return service.info()


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(..., description="上传 .pdf/.md/.txt 文档")) -> dict[str, Any]:
    service = get_rag_service()
    try:
        return await service.upload_document(file)
    except DocumentUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传并增量入库失败：{exc}") from exc


@app.post("/knowledge-base/rebuild")
def rebuild_knowledge_base() -> dict[str, Any]:
    service = get_rag_service()
    try:
        return service.rebuild_knowledge_base()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"全量重建知识库失败：{exc}") from exc


@app.post("/search")
def search(payload: SearchRequest) -> dict[str, Any]:
    service = get_rag_service()
    return {
        "query": payload.query,
        "top_k": payload.top_k,
        "results": service.search(payload.query, payload.top_k),
    }


@app.post("/keyword-search")
def keyword_search(payload: SearchRequest) -> dict[str, Any]:
    service = get_rag_service()
    return {
        "query": payload.query,
        "top_k": payload.top_k,
        "retrieval": "bm25_child",
        "results": service.keyword_search(payload.query, payload.top_k),
    }


@app.post("/hybrid-search")
def hybrid_search(payload: HybridSearchRequest) -> dict[str, Any]:
    service = get_rag_service()
    return {
        "query": payload.query,
        "top_k": payload.top_k,
        "retrieval": "rrf_hybrid_child",
        "vector_top_k": payload.vector_top_k,
        "keyword_top_k": payload.keyword_top_k,
        "rrf_k": payload.rrf_k,
        "results": service.hybrid_search(
            payload.query,
            payload.top_k,
            payload.vector_top_k,
            payload.keyword_top_k,
            payload.rrf_k,
        ),
    }


@app.post("/rerank-search")
def rerank_search(payload: RerankSearchRequest) -> dict[str, Any]:
    service = get_rag_service()
    try:
        results = service.rerank_search(
            payload.query,
            payload.top_k,
            payload.vector_top_k,
            payload.keyword_top_k,
            payload.hybrid_top_k,
            payload.rrf_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "query": payload.query,
        "top_k": payload.top_k,
        "retrieval": "hybrid_rerank_child",
        "vector_top_k": payload.vector_top_k,
        "keyword_top_k": payload.keyword_top_k,
        "hybrid_top_k": payload.hybrid_top_k,
        "rrf_k": payload.rrf_k,
        "results": results,
    }


@app.post("/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    service = get_rag_service()
    try:
        return service.chat(
            payload.question,
            payload.top_k,
            payload.query_mode,
            payload.retrieval_mode,
            payload.reasoning,
            payload.session_id,
            payload.use_memory,
            payload.context_window,
            payload.document_id,
            payload.file_name,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek 调用失败：{exc}") from exc


@app.post("/web-search")
def web_search(payload: SearchRequest) -> dict[str, Any]:
    service = get_rag_service()
    try:
        tool_result = service.web_search_with_trace(payload.query, payload.top_k)
        return {
            "query": payload.query,
            "top_k": payload.top_k,
            "provider": tool_result.get("provider"),
            "fallback_from": tool_result.get("fallback_from"),
            "status": tool_result.get("status"),
            "retry_count": tool_result.get("retry_count", 0),
            "result_count": tool_result.get("result_count", 0),
            "duration_ms": tool_result.get("duration_ms", 0),
            "errors": tool_result.get("errors", []),
            "results": tool_result.get("results", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"联网搜索失败：{exc}") from exc


@app.post("/web-chat")
def web_chat(payload: ChatRequest) -> dict[str, Any]:
    service = get_rag_service()
    try:
        return service.web_chat(
            payload.question,
            payload.top_k,
            payload.reasoning,
            payload.session_id,
            payload.use_memory,
            payload.context_window,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"联网问答失败：{exc}") from exc


@app.post("/agent-chat")
def agent_chat(payload: ChatRequest) -> dict[str, Any]:
    service = get_rag_service()
    try:
        return service.react_chat(
            payload.question,
            payload.top_k,
            payload.reasoning,
            payload.session_id,
            payload.use_memory,
            payload.context_window,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ReAct Agent 调用失败：{exc}") from exc


@app.post("/memory/clear")
def clear_memory(payload: MemoryClearRequest) -> dict[str, Any]:
    service = get_rag_service()
    return service.clear_memory(payload.session_id)
