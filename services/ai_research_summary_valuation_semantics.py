from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from services.unified_research_contract import UnifiedResearchContext


def merged_unified_data_quality(unified: UnifiedResearchContext) -> dict[str, Any]:
    ci = unified.company_intelligence or {}
    ci_dq = ci.get("data_quality") or {}
    top_dq = unified.data_quality or {}
    return {**ci_dq, **top_dq}


def _compact_metrics(unified: UnifiedResearchContext) -> Tuple[dict[str, Any], ...]:
    ci = unified.company_intelligence or {}
    metrics: list[dict[str, Any]] = []
    for metric in ci.get("valuation_metrics") or ():
        if not isinstance(metric, Mapping):
            continue
        current_value = metric.get("current_value")
        if current_value is None:
            continue
        label = str(metric.get("label") or metric.get("code") or "").strip()
        if not label:
            continue
        metrics.append(
            {
                "code": metric.get("code"),
                "label": label,
                "current_value": current_value,
            }
        )
    return tuple(metrics)


def _format_metric_values_phrase(metrics: Tuple[dict[str, Any], ...]) -> str:
    parts: list[str] = []
    for metric in metrics[:5]:
        label = str(metric.get("label") or metric.get("code") or "").strip()
        value = metric.get("current_value")
        if not label or value is None:
            continue
        if isinstance(value, float):
            formatted = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            formatted = str(value)
        parts.append(f"{label} {formatted}")
    return ", ".join(parts)


@dataclass(frozen=True)
class ValuationSemantics:
    current_metrics_available: bool
    historical_median_available: bool
    peer_comparison_available: bool
    relative_valuation_context_limited: bool
    thesis_valuation_context_code: Optional[str]
    available_metrics: Tuple[dict[str, Any], ...]

    def recommended_summary_framing(self, *, include_values: bool = False) -> Optional[str]:
        if self.current_metrics_available and self.relative_valuation_context_limited:
            if include_values:
                values_phrase = _format_metric_values_phrase(self.available_metrics)
                if values_phrase:
                    return (
                        f"Hibrit yıllık değerleme oranları ({values_phrase}) mevcut; ancak tarihsel "
                        "medyan ve benzer şirket karşılaştırması olmadığı için göreceli "
                        "değerleme yorumu sınırlı."
                    )
            labels = ", ".join(
                str(metric.get("label") or metric.get("code") or "").strip()
                for metric in self.available_metrics[:5]
                if str(metric.get("label") or metric.get("code") or "").strip()
            )
            if labels:
                return (
                    f"Hibrit yıllık değerleme oranları ({labels}) mevcut; ancak tarihsel "
                    "medyan ve benzer şirket karşılaştırması olmadığı için göreceli "
                    "değerleme yorumu sınırlı."
                )
            return (
                "Hibrit yıllık değerleme oranları mevcut; ancak tarihsel medyan ve benzer "
                "şirket karşılaştırması olmadığı için göreceli değerleme yorumu sınırlı."
            )
        if not self.current_metrics_available:
            return "Mevcut değerleme oranları hesaplanamıyor."
        return None

    def to_dict(self) -> dict[str, Any]:
        thesis_code = self.thesis_valuation_context_code
        metrics_missing_interpretation = (
            thesis_code == "VALUATION_UNAVAILABLE" and self.current_metrics_available
        )
        payload = {
            "current_valuation_metrics_available": self.current_metrics_available,
            "historical_valuation_median_available": self.historical_median_available,
            "peer_valuation_comparison_available": self.peer_comparison_available,
            "relative_valuation_context_limited": self.relative_valuation_context_limited,
            "thesis_valuation_context_code": thesis_code,
            "thesis_valuation_context_scope": (
                "relative_historical_peer_interpretation_only"
                if metrics_missing_interpretation
                else "standard"
            ),
            "thesis_valuation_context_does_not_mean_metrics_missing": (
                metrics_missing_interpretation
            ),
            "available_valuation_metrics": list(self.available_metrics),
        }
        framing = self.recommended_summary_framing()
        if framing:
            payload["recommended_valuation_summary_framing"] = framing
        return payload


def valuation_semantics_from_snapshot(payload: Optional[Mapping[str, Any]]) -> Optional[ValuationSemantics]:
    if not payload:
        return None
    available_metrics: list[dict[str, Any]] = []
    for metric in payload.get("available_valuation_metrics") or ():
        if not isinstance(metric, Mapping):
            continue
        current_value = metric.get("current_value")
        if current_value is None:
            continue
        label = str(metric.get("label") or metric.get("code") or "").strip()
        if not label:
            continue
        available_metrics.append(
            {
                "code": metric.get("code"),
                "label": label,
                "current_value": current_value,
            }
        )
    return ValuationSemantics(
        current_metrics_available=bool(payload.get("current_valuation_metrics_available")),
        historical_median_available=bool(payload.get("historical_valuation_median_available")),
        peer_comparison_available=bool(payload.get("peer_valuation_comparison_available")),
        relative_valuation_context_limited=bool(payload.get("relative_valuation_context_limited")),
        thesis_valuation_context_code=(
            str(payload.get("thesis_valuation_context_code") or "").strip() or None
        ),
        available_metrics=tuple(available_metrics),
    )


def authoritative_valuation_summary(semantics: ValuationSemantics) -> Optional[str]:
    """Deterministic valuation prose when current metrics exist."""
    if not semantics.current_metrics_available:
        return None
    if semantics.relative_valuation_context_limited:
        return semantics.recommended_summary_framing(include_values=True)
    return None


def derive_valuation_semantics(unified: UnifiedResearchContext) -> ValuationSemantics:
    dq = merged_unified_data_quality(unified)
    available_metrics = _compact_metrics(unified)
    current_metrics_available = bool(dq.get("valuation_available")) or bool(available_metrics)
    historical_median_available = bool(dq.get("historical_valuation_available"))
    peer_comparison_available = bool(dq.get("peer_data_available"))
    relative_valuation_context_limited = not historical_median_available
    thesis = unified.investment_thesis or {}
    thesis_code = str(thesis.get("valuation_context") or "").strip() or None
    return ValuationSemantics(
        current_metrics_available=current_metrics_available,
        historical_median_available=historical_median_available,
        peer_comparison_available=peer_comparison_available,
        relative_valuation_context_limited=relative_valuation_context_limited,
        thesis_valuation_context_code=thesis_code,
        available_metrics=available_metrics,
    )
