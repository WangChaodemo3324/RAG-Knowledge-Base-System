"""Lightweight in-process rate limiting (no Redis): sliding-window per client IP.

- /search /keyword-search /hybrid-search /rerank-search /chat* /web-search:
  general bucket
- admin endpoints (upload/rebuild/prune/delete/retry/clear): stricter bucket

Configure via RAG_RATE_LIMIT_PER_MIN (default 120) and
RAG_ADMIN_RATE_LIMIT_PER_MIN (default 20). Set to 0 to disable (tests/local).
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend.core.logging import get_logger

logger = get_logger(__name__)

GENERAL_LIMIT = int(os.getenv("RAG_RATE_LIMIT_PER_MIN", "120"))
ADMIN_LIMIT = int(os.getenv("RAG_ADMIN_RATE_LIMIT_PER_MIN", "20"))
_WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_last_sweep = 0.0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request, bucket: str = "general") -> None:
    """Raise 429 when the caller exceeds its window quota. Sweep old entries
    opportunistically to bound memory."""
    global _last_sweep
    limit = ADMIN_LIMIT if bucket == "admin" else GENERAL_LIMIT
    if limit <= 0:
        return

    key = (_client_ip(request), bucket)
    now = time.monotonic()
    with _lock:
        window = _hits[key]
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= limit:
            retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
            logger.warning("rate limit hit: ip=%s bucket=%s", key[0], bucket)
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请稍后再试",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
        window.append(now)

        if now - _last_sweep > 300:  # periodic full sweep bounds memory
            for k in list(_hits.keys()):
                q = _hits[k]
                while q and now - q[0] > _WINDOW_SECONDS:
                    q.popleft()
                if not q:
                    _hits.pop(k, None)
            _last_sweep = now


def reset_rate_limiter() -> None:
    """Test helper."""
    with _lock:
        _hits.clear()
        global _last_sweep
        _last_sweep = 0.0
