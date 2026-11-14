from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def doc_to_source(doc: Any, index: int) -> dict[str, Any]:
    metadata = getattr(doc, "metadata", {})
    source = metadata.get("source", "") if metadata else ""
    return {
        "index": index,
        "source": Path(source).name if source else "",
        "chunk_id": metadata.get("chunk_id", ""),
        "parent_id": metadata.get("parent_id", ""),
        "retrieval_level": metadata.get("retrieval_level", ""),
        "matched_child_id": metadata.get("matched_child_id", ""),
        "matched_child_preview": metadata.get("matched_child_preview", ""),
        "retrieval_mode": metadata.get("retrieval_mode", ""),
        "rrf_score": metadata.get("rrf_score", ""),
        "rerank_score": metadata.get("rerank_score", ""),
        "rerank_model": metadata.get("rerank_model", ""),
        "vector_rank": metadata.get("vector_rank", ""),
        "bm25_rank": metadata.get("bm25_rank", ""),
        "retrievers": metadata.get("retrievers", ""),
        "chunk_index": metadata.get("chunk_index", ""),
        "chunk_total": metadata.get("chunk_total", ""),
        "parent_index": metadata.get("parent_index", ""),
        "parent_total": metadata.get("parent_total", ""),
        "page_number": metadata.get("page_number", ""),
        "section_title": metadata.get("section_title", ""),
        "file_hash_short": metadata.get("file_hash_short", ""),
        "metadata": metadata,
        "content": doc.page_content,
        "preview": doc.page_content[:220],
    }


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def source_content(source: dict[str, Any]) -> str:
    return str(source.get("content") or source.get("snippet") or source.get("preview") or "")


def format_agent_sources(sources: list[dict[str, Any]], limit: int = 900) -> str:
    if not sources:
        return "暂无资料。"
    blocks: list[str] = []
    for source in sources:
        title = source.get("title") or source.get("source") or "资料片段"
        url = f"\nURL: {source.get('url')}" if source.get("url") else ""
        content = source_content(source)[:limit]
        blocks.append(
            f"[{source['index']}] {title}\n"
            f"工具: {source.get('tool')}\n"
            f"查询: {source.get('query')}{url}\n"
            f"内容: {content}"
        )
    return "\n\n".join(blocks)
