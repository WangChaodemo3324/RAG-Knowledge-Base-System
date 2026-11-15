"""In-process metrics for the lightweight observability stack.

Counters and rolling latency windows kept in memory; exposed via GET /metrics.
No external monitoring containers — sufficient for single-node deployment.
Stage timings are recorded where the work happens (vector/bm25/rerank/embedding).
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict, deque
from typing import Any

_started_at = time.time()
_lock = threading.Lock()
_requests_by_status: defaultdict[int, int] = defaultdict(int)
_request_total = 0
_latency_by_route: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))
_stages: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))


def observe_request(route: str, status_code: int, duration_ms: float) -> None:
    global _request_total
    with _lock:
        _request_total += 1
        _requests_by_status[status_code] += 1
        _latency_by_route[route].append(duration_ms)


def record_stage(stage: str, duration_ms: float) -> None:
    with _lock:
        _stages[stage].append(duration_ms)


def _summary(samples: deque[float]) -> dict[str, Any] | None:
    if not samples:
        return None
    ordered = sorted(samples)
    p50 = ordered[(len(ordered) - 1) // 2]
    p95 = ordered[min(int(0.95 * len(ordered)), len(ordered) - 1)]
    return {
        "count": len(ordered),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "mean_ms": round(statistics.mean(ordered), 1),
    }


def snapshot() -> dict[str, Any]:
    with _lock:
        by_route = {route: _summary(window) for route, window in sorted(_latency_by_route.items())}
        by_route = {route: value for route, value in by_route.items() if value}
        stages = {stage: _summary(window) for stage, window in sorted(_stages.items())}
        stages = {stage: value for stage, value in stages.items() if value}
        statuses = {str(code): count for code, count in sorted(_requests_by_status.items())}
        return {
            "uptime_s": round(time.time() - _started_at, 1),
            "requests": {
                "total": _request_total,
                "by_status": statuses,
                "error_rate": round(
                    sum(count for code, count in _requests_by_status.items() if code >= 500) / _request_total,
                    4,
                )
                if _request_total
                else 0.0,
            },
            "latency_by_route": by_route,
            "stages": stages,
        }


def index_task_stats() -> dict[str, int] | None:
    """Index task success rate straight from PostgreSQL (None when DB is down)."""
    try:
        from sqlalchemy import func, select

        from backend.db.models import IndexTask
        from backend.db import engine

        with engine.connect() as connection:
            rows = connection.execute(
                select(IndexTask.status, func.count()).group_by(IndexTask.status)
            ).all()
        return {status: count for status, count in rows}
    except Exception:
        return None
