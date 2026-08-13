from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WATCH = "WATCH"
    HIGH = "HIGH"


class DiagnosticCategory(str, Enum):
    CONCENTRATION = "CONCENTRATION"
    DIVERSIFICATION = "DIVERSIFICATION"
    CASH = "CASH"
    PERFORMANCE = "PERFORMANCE"
    DRAWDOWN = "DRAWDOWN"
    BENCHMARK = "BENCHMARK"
    DATA_QUALITY = "DATA_QUALITY"
    NABI_CONTEXT = "NABI_CONTEXT"


class DiagnosticConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class PortfolioDiagnostic:
    code: str
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    title: str
    summary: str
    evidence: Dict[str, Any]
    metric_value: Optional[float]
    threshold: Optional[float]
    affected_symbols: List[str]
    confidence: DiagnosticConfidence
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "summary": self.summary,
            "evidence": dict(self.evidence),
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "affected_symbols": list(self.affected_symbols),
            "confidence": self.confidence.value,
            "source": self.source,
        }


@dataclass(frozen=True)
class PortfolioDiagnosticsView:
    portfolio_id: str
    generated_at: str
    diagnostics: List[PortfolioDiagnostic]
    high_count: int
    watch_count: int
    info_count: int
    data_quality_ok: bool
    comparable_performance: bool
    benchmark_available: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "generated_at": self.generated_at,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "high_count": self.high_count,
            "watch_count": self.watch_count,
            "info_count": self.info_count,
            "data_quality_ok": self.data_quality_ok,
            "comparable_performance": self.comparable_performance,
            "benchmark_available": self.benchmark_available,
        }
