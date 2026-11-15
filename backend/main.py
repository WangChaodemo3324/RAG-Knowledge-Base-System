from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool as await_to_thread

from backend.core import metrics as app_metrics
from backend.core.auth import require_admin
from backend.core.config import CORS_ORIGINS
from backend.core.logging import configure_logging, get_logger, request_id_var
from backend.core.rate_limit import check_rate_limit
from backend.db import engine
from backend.indexing.index_pipeline import DocumentNotFoundError
from backend.indexing.pg_store import VersionError
from backend.schemas import (
    ChatRequest,
    HybridSearchRequest,
    MemoryClearRequest,
    RerankSearchRequest,
    SearchRequest,
)
from backend.services.document_service import DocumentUploadError
from backend.services.rag_service import get_rag_service

configure_logging()
logger = get_logger(__name__)

app = FastAPI(title="LangChain RAG API", version="2.0.0")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
WEB_INDEX = FRONTEND_DIR / "index.html"

app.add_middleware(
    CORSMiddleware,
    # unset RAG_CORS_ORIGINS keeps the local-dev wildcard (credentials disabled);
    # production must set an explicit origin allowlist
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ADMIN_PATHS = {
    "/documents/upload",
    "/knowledge-base/rebuild",
    "/index/prune",
    "/memory/clear",
}
_RATE_EXEMPT = {"/health", "/metrics", "/docs", "/openapi.json", "/", "/info"}
# static prefixes are exempt too
_RATE_EXEMPT_PREFIXES = ("/src/",)


@app.middleware("http")
async def request_context_middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_var.set(request_id)
    started = time.perf_counter()

    path = request.url.path
    if request.method in {"POST", "DELETE", "PUT"} and path not in _RATE_EXEMPT and not any(
        path.startswith(prefix) for prefix in _RATE_EXEMPT_PREFIXES
    ):
        try:
            check_rate_limit(request, bucket="admin" if path in _ADMIN_PATHS else "general")
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled exception", extra={"event": "unhandled"})
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请查看服务端日志"})
    duration_ms = int((time.perf_counter() - started) * 1000)
    app_metrics.observe_request(path, response.status_code, duration_ms)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s %sms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={"event": "http_access", "route": request.url.path, "duration_ms": duration_ms, "status": response.status_code},
    )
    return response


def db_health() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        connected = True
    except Exception as exc:
        connected = False
        # exception detail goes to logs only — /health is unauthenticated and
        # must not disclose host/user/driver information
        logger.warning("database health check failed: %s", exc)
    active = ""
    if connected:
        try:
            from sqlalchemy import select

            from backend.db.models import IndexVersion

            with engine.connect() as connection:
                row = connection.execute(
                    select(IndexVersion.name).where(IndexVersion.is_active.is_(True))
                ).first()
            active = row[0] if row else ""
        except Exception:
            active = ""
    return {"connected": connected, "detail": "", "active_version": active}


app.mount("/src", StaticFiles(directory=FRONTEND_DIR / "src"), name="frontend-src")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    response = FileResponse(WEB_INDEX)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    database = db_health()
    return {
        "status": "ok" if database["connected"] else "degraded",
        "service": "LangChain RAG API",
        "database": database,
        "docs": "/docs",
        "endpoints": [
            "/info",
            "/index/versions",
            "/index/prune",
            "/documents",
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


@app.post("/documents/upload-batch", dependencies=[Depends(require_admin)])
async def upload_documents_batch(files: list[UploadFile] = File(..., description="批量上传 .pdf/.md/.txt 文档")) -> dict[str, Any]:
    """Batch upload: each file is saved and indexed independently; per-file
    failures (bad extension, parse error, size limit) never abort the batch."""
    service = get_rag_service()
    try:
        return await service.upload_documents_batch(files)
    except DocumentUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except VersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("batch upload failed")
        raise HTTPException(status_code=500, detail="批量上传失败") from exc


@app.get("/documents")
def list_documents() -> dict[str, Any]:
    return get_rag_service().list_documents()


@app.delete("/documents/{file_name}", dependencies=[Depends(require_admin)])
def delete_document(file_name: str) -> dict[str, Any]:
    """Remove a document from the active index; its source file is moved to
    `<data_dir>/.trash/` (recoverable) and all index rows are deleted in one
    transaction. BM25 rebuilds automatically via the version signature."""
    try:
        return get_rag_service().delete_document(file_name)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("document delete failed")
        raise HTTPException(status_code=500, detail="文档删除失败") from exc


@app.post("/documents/{file_name}/retry", dependencies=[Depends(require_admin)])
def retry_document(file_name: str) -> dict[str, Any]:
    """Re-index a previously failed (or stale) document from its source file."""
    try:
        return get_rag_service().retry_document(file_name)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("document retry failed")
        raise HTTPException(status_code=500, detail="文档重试失败") from exc


@app.post("/index/prune", dependencies=[Depends(require_admin)])
def prune_index_versions() -> dict[str, Any]:
    """Delete retired index versions beyond the retention window (active version
    is never touched). Helps bound storage growth on frequent rebuilds."""
    service = get_rag_service()
    try:
        return await_to_thread(service.knowledge_base.prune_retired_versions)
    except Exception as exc:
        logger.exception("prune failed")
        raise HTTPException(status_code=500, detail="清理历史版本失败") from exc


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    snapshot = app_metrics.snapshot()
    tasks = app_metrics.index_task_stats()
    if tasks:
        snapshot["index_tasks"] = tasks
    return snapshot


@app.get("/index/versions")
def index_versions() -> dict[str, Any]:
    service = get_rag_service()
    return service.knowledge_base.info()


@app.get("/info")
def info() -> dict[str, Any]:
    service = get_rag_service()
    return service.info()


@app.post("/documents/upload", dependencies=[Depends(require_admin)])
async def upload_document(file: UploadFile = File(..., description="上传 .pdf/.md/.txt 文档")) -> dict[str, Any]:
    service = get_rag_service()
    try:
        return await service.upload_document(file)
    except VersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="上传并增量入库失败") from exc


@app.post("/knowledge-base/rebuild", dependencies=[Depends(require_admin)])
def rebuild_knowledge_base() -> dict[str, Any]:
    service = get_rag_service()
    try:
        return service.rebuild_knowledge_base()
    except VersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("rebuild failed")
        raise HTTPException(status_code=500, detail="全量重建知识库失败") from exc


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
        raise HTTPException(status_code=502, detail="大模型调用失败") from exc


@app.post("/chat/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """SSE streaming variant of /chat for the knowledge-base path.

    Non-streaming /chat remains unchanged and still handles full routing.
    SSE events: sources → token* → done, plus error events; [DONE] terminator.
    """
    import json as _json

    service = get_rag_service()

    def event_stream():
        try:
            for event in service.chat_stream(
                payload.question,
                payload.top_k,
                payload.retrieval_mode,
                payload.reasoning,
                payload.session_id,
                payload.use_memory,
                payload.context_window,
                payload.file_name,
            ):
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except GeneratorExit:
            raise
        except Exception:
            logger.exception("chat_stream endpoint failed")
            yield f"data: {_json.dumps({'type': 'error', 'detail': '流式服务异常'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


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
        raise HTTPException(status_code=502, detail="联网搜索失败") from exc


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
        raise HTTPException(status_code=502, detail="联网问答失败") from exc


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
        raise HTTPException(status_code=502, detail="ReAct Agent 调用失败") from exc


@app.post("/memory/clear", dependencies=[Depends(require_admin)])
def clear_memory(payload: MemoryClearRequest) -> dict[str, Any]:
    service = get_rag_service()
    return service.clear_memory(payload.session_id)
