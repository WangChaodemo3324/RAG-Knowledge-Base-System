from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_env_file() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(BASE_DIR / "resource data")))
DATABASE_URL = os.getenv("RAG_DATABASE_URL", "postgresql+psycopg://rag:rag@127.0.0.1:5433/rag")
DB_POOL_SIZE = int(os.getenv("RAG_DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("RAG_DB_MAX_OVERFLOW", "5"))
DB_POOL_RECYCLE_SECONDS = int(os.getenv("RAG_DB_POOL_RECYCLE_SECONDS", "1800"))
ADMIN_API_KEY = os.getenv("RAG_ADMIN_API_KEY", "").strip()
# comma-separated origin allowlist; unset keeps the local-dev wildcard
CORS_ORIGINS = [origin.strip() for origin in os.getenv("RAG_CORS_ORIGINS", "").split(",") if origin.strip()]
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt"}
FALLBACK_DATA_FILE = BASE_DIR / "resource data" / "生产环境发布与回滚操作规范.md"
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
PARENT_CHUNK_SIZE = int(os.getenv("RAG_PARENT_CHUNK_SIZE", "1800"))
PARENT_CHUNK_OVERLAP = int(os.getenv("RAG_PARENT_CHUNK_OVERLAP", "180"))
CHUNKING_STRATEGY = os.getenv("RAG_CHUNKING_STRATEGY", "parent_child_semantic_boundary")
CHILD_CHUNKING_MODE = os.getenv("RAG_CHILD_CHUNKING_MODE", "semantic_boundary")
SEMANTIC_MIN_CHUNK_SIZE = int(os.getenv("RAG_SEMANTIC_MIN_CHUNK_SIZE", "220"))
CHUNK_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "//", ""]
RERANK_MODEL_NAME = os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-base")
RERANK_MAX_LENGTH = int(os.getenv("RAG_RERANK_MAX_LENGTH", "512"))
EMBEDDING_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_MODEL_BACKEND = os.getenv("RAG_EMBEDDING_BACKEND", "onnx")
LOCAL_EMBEDDING_MODEL = os.getenv("RAG_LOCAL_EMBEDDING_MODEL", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "tavily").strip().lower()
WEB_SEARCH_FALLBACK = os.getenv("WEB_SEARCH_FALLBACK", "duckduckgo").strip().lower()
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_DEPTH = os.getenv("WEB_SEARCH_DEPTH", "basic").strip().lower()
WEB_SEARCH_INCLUDE_RAW_CONTENT = os.getenv("WEB_SEARCH_INCLUDE_RAW_CONTENT", "false").strip().lower() == "true"
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "15"))
WEB_SEARCH_TAVILY_MAX_RETRIES = int(os.getenv("WEB_SEARCH_TAVILY_MAX_RETRIES", "2"))
WEB_SEARCH_REQUIRE_TAVILY = os.getenv("WEB_SEARCH_REQUIRE_TAVILY", "false").strip().lower() == "true"


def get_deepseek_config() -> dict[str, str]:
    """DeepSeek configuration comes exclusively from the environment.

    The Phase-1 AST fallback that parsed constants out of legacy/rag.py was
    removed: a dead file must never be able to influence production config.
    """
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    }
