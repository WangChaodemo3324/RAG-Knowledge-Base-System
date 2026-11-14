from __future__ import annotations

import ast
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
CHROMA_DIR = Path(os.getenv("RAG_CHROMA_DIR", str(BASE_DIR / "chroma_db")))
MANIFEST_FILE = Path(os.getenv("RAG_MANIFEST_FILE", str(BASE_DIR / "manifest.json")))
PARENT_STORE_FILE = Path(os.getenv("RAG_PARENT_STORE_FILE", str(BASE_DIR / "parent_store.json")))
CHILD_STORE_FILE = Path(os.getenv("RAG_CHILD_STORE_FILE", str(BASE_DIR / "child_store.json")))
CHROMA_COLLECTION_NAME = os.getenv("RAG_CHROMA_COLLECTION_NAME", "rag_documents")
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


def _load_code_config() -> dict[str, str]:
    """Read optional DeepSeek constants from rag.py without executing it."""
    config: dict[str, str] = {}
    rag_file = BASE_DIR / "legacy" / "rag.py"
    if not rag_file.exists():
        return config

    try:
        tree = ast.parse(rag_file.read_text(encoding="utf-8"))
    except Exception:
        return config

    wanted = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                config[target.id] = node.value.value
    return config


def get_deepseek_config() -> dict[str, str]:
    code_config = _load_code_config()
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY") or code_config.get("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL") or code_config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL") or code_config.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    }
