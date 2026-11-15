from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import BASE_DIR
from backend.services.routing.route_schema import (
    EvidenceDecision,
    QueryFeatures,
    RouteDecision,
)


class RouteTraceLogger:
    """Append lightweight route observations to a local JSONL file."""

    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path or BASE_DIR / "route_logs.jsonl"

    def log(
        self,
        query: str,
        query_mode: str,
        decision: RouteDecision,
        duration_ms: int,
        features: QueryFeatures | None = None,
        evidence: EvidenceDecision | None = None,
    ) -> None:
        try:
            record: dict[str, Any] = {
                "time": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "query_mode": query_mode,
                "route": decision.route,
                "route_reason": decision.reason,
                "route_confidence": decision.confidence,
                "route_router": decision.router,
                "duration_ms": duration_ms,
            }
            if features is not None:
                record["features"] = features.to_dict()
            if evidence is not None:
                record["evidence"] = evidence.to_dict()

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            return
