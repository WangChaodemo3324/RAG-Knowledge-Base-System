from __future__ import annotations

from enum import Enum


class ChatQueryMode(str, Enum):
    """User-facing chat modes selected by the frontend."""

    DOCUMENT = "DOCUMENT"
    AUTO_DOCUMENT = "AUTO_DOCUMENT"
    OPEN_CHAT = "OPEN_CHAT"


class ExecutionMode(str, Enum):
    """Backend execution modes selected by the chat orchestrator."""

    RETRIEVAL = "RETRIEVAL"
    REACT_AGENT = "REACT_AGENT"
    CLARIFICATION = "CLARIFICATION"
    GRAPH_ONLY = "GRAPH_ONLY"
    GRAPH_THEN_EVIDENCE = "GRAPH_THEN_EVIDENCE"


def parse_chat_query_mode(value: str | ChatQueryMode | None) -> ChatQueryMode:
    if isinstance(value, ChatQueryMode):
        return value
    if not value:
        return ChatQueryMode.AUTO_DOCUMENT
    normalized = str(value).strip().upper()
    try:
        return ChatQueryMode(normalized)
    except ValueError as exc:
        supported = ", ".join(mode.value for mode in ChatQueryMode)
        raise RuntimeError(f"Unsupported query_mode: {value}. Supported modes: {supported}") from exc
