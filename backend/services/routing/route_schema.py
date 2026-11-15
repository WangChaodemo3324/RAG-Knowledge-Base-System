from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KB_ONLY = "KB_ONLY"
WEB_ONLY = "WEB_ONLY"
KB_THEN_WEB = "KB_THEN_WEB"
NO_EVIDENCE = "NO_EVIDENCE"
DIRECT_LLM = "DIRECT_LLM"
CLARIFY = "CLARIFY"


@dataclass(frozen=True)
class QueryFeatures:
    query_length: int
    has_selected_document: bool = False
    has_file_context: bool = False
    explicit_web: bool = False
    has_current_time_need: bool = False
    has_company_domain_hint: bool = False
    has_private_internal_hint: bool = False
    is_math_like: bool = False
    is_chat_like: bool = False
    is_instruction_task: bool = False
    is_vague_reference: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceDecision:
    sufficient: bool
    reason: str
    result_count: int = 0
    valid_count: int = 0
    top_score: float | None = None
    top_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    confidence: float = 1.0
    router: str = "rule"
    tool_traces: list[dict[str, Any]] = field(default_factory=list)
    features: QueryFeatures | None = None
    evidence: EvidenceDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "route": self.route,
            "route_reason": self.reason,
            "tool_traces": self.tool_traces,
            "route_confidence": self.confidence,
            "route_router": self.router,
        }
        if self.features is not None:
            data["route_features"] = self.features.to_dict()
        if self.evidence is not None:
            data["route_evidence"] = self.evidence.to_dict()
        return data
