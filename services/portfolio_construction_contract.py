from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ConcentrationMetrics:
    top1_symbol: Optional[str]
    top1_weight_pct: Optional[float]
    top3_weight_pct: Optional[float]
    top5_weight_pct: Optional[float]
    hhi_proxy: Optional[float]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExposureOverlapSignal:
    overlap_type: str
    key: str
    label: str
    symbol_count: int
    combined_weight_pct: Optional[float]
    symbols: Tuple[str, ...]
    look_through_status: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskBudgetDimension:
    dimension: str
    current_value: Optional[float]
    threshold: Optional[float]
    status: str
    evidence: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioConstructionView:
    concentration: ConcentrationMetrics
    sector_allocation: Tuple[Dict[str, Any], ...]
    country_allocation: Tuple[Dict[str, Any], ...]
    institution_allocation: Tuple[Dict[str, Any], ...]
    participation_allocation: Tuple[Dict[str, Any], ...]
    research_coverage_allocation: Tuple[Dict[str, Any], ...]
    currency_allocation: Tuple[Dict[str, Any], ...]
    cash_weight_pct: Optional[float]
    priced_weight_pct: Optional[float]
    unpriced_weight_pct: Optional[float]
    overlap_signals: Tuple[ExposureOverlapSignal, ...]
    risk_budget: Tuple[RiskBudgetDimension, ...]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceLimitGap:
    dimension: str
    current_value: Optional[float]
    reference_limit: Optional[float]
    gap_pp: Optional[float]
    status: str
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    scenario_label: str
    shock_pct: Optional[float]
    affected_positions: Tuple[Dict[str, Any], ...]
    current_priced_value: Optional[float]
    shocked_value: Optional[float]
    portfolio_impact_abs: Optional[float]
    portfolio_impact_pct: Optional[float]
    excluded_unpriced_symbols: Tuple[str, ...]
    coverage_pct: Optional[float]
    assumptions: Tuple[str, ...]
    limitations: Tuple[str, ...]
    is_forecast: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["is_forecast"] = False
        payload["label"] = "SCENARIO, NOT FORECAST"
        return payload


@dataclass(frozen=True)
class DecisionTimelineEntry:
    journal_id: str
    symbol: str
    decision_date: str
    decision_type: str
    title: str
    monitor_event_ids: Tuple[str, ...]
    thesis_change: Optional[str]
    position_change: Optional[str]
    outcome_status: Optional[str]
    outcome_pct: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
