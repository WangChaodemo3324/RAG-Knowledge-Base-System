"""Admin API key authentication for management endpoints."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from backend.core.config import ADMIN_API_KEY


async def require_admin(
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> None:
    """Admin guard. Auth is disabled when RAG_ADMIN_API_KEY is unset (local dev)."""
    if not ADMIN_API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理端点需要有效的 X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
