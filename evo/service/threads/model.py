from __future__ import annotations

from dataclasses import dataclass
from lazyllm.tracing.datamodel.structured import StructuredTrace


@dataclass
class TraceContext:
    scene: str
    report_id: str
    dataset_id: str
    case_id: str
    knowledge_base_id: str
    algorithm_version: str


@dataclass
class TraceSummary:
    status: str
    latency_ms: float | None
    round_count: int
    tool_call_count: int
    retrieval_count: int
    rerank_count: int


@dataclass
class TraceDetailResponse:
    trace_id: str
    trace_status: str
    context: TraceContext
    query: str
    summary: TraceSummary
    trace: StructuredTrace | None


@dataclass
class TraceCompareResponse:
    case_id: str
    query: str
    a: TraceDetailResponse
    b: TraceDetailResponse
