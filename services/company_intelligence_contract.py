from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_utils import serialize_optional


@dataclass(frozen=True)
class IntelligenceProvenance:
    provider: str
    data_family: str
    source_period: Optional[str] = None
    retrieved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "data_family": self.data_family,
            "source_period": self.source_period,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True)
class IntelligenceObservation:
    code: str
    status: str
    statement: str
    metric: Optional[str] = None
    value: Optional[float] = None
    comparison_value: Optional[float] = None
    direction: Optional[str] = None
    evidence: Tuple[Tuple[str, Any], ...] = ()
    source: Optional[str] = None
    confidence: str = "MEDIUM"
    period: Optional[str] = None
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "statement": self.statement,
            "metric": self.metric,
            "value": self.value,
            "comparison_value": self.comparison_value,
            "direction": self.direction,
            "evidence": dict(self.evidence),
            "source": self.source,
            "confidence": self.confidence,
            "period": self.period,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class BusinessSnapshot:
    symbol: str
    company_name: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    exchange: Optional[str]
    market_cap: Optional[float]
    currency: Optional[str]
    country: Optional[str]
    description: Optional[str]
    ceo: Optional[str]
    website: Optional[str]
    reporting_currency: Optional[str]
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "industry": self.industry,
            "exchange": self.exchange,
            "market_cap": self.market_cap,
            "currency": self.currency,
            "country": self.country,
            "description": self.description,
            "ceo": self.ceo,
            "website": self.website,
            "reporting_currency": self.reporting_currency,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class MetricTrendPoint:
    metric: str
    latest_value: Optional[float]
    previous_value: Optional[float]
    absolute_change: Optional[float]
    pct_change: Optional[float]
    direction: str
    period: Optional[str]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "latest_value": self.latest_value,
            "previous_value": self.previous_value,
            "absolute_change": self.absolute_change,
            "pct_change": self.pct_change,
            "direction": self.direction,
            "period": self.period,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class FinancialTrendsSection:
    trends: Tuple[MetricTrendPoint, ...]
    observations: Tuple[IntelligenceObservation, ...]
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trends": [item.to_dict() for item in self.trends],
            "observations": [item.to_dict() for item in self.observations],
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class EarningsExpectations:
    expectations_available: bool
    revenue_actual: Optional[float] = None
    revenue_estimate: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None
    eps_actual: Optional[float] = None
    eps_estimate: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    estimate_revision_direction: Optional[str] = None
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expectations_available": self.expectations_available,
            "revenue_actual": self.revenue_actual,
            "revenue_estimate": self.revenue_estimate,
            "revenue_surprise_pct": self.revenue_surprise_pct,
            "eps_actual": self.eps_actual,
            "eps_estimate": self.eps_estimate,
            "eps_surprise_pct": self.eps_surprise_pct,
            "estimate_revision_direction": self.estimate_revision_direction,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class EarningsSection:
    period: Optional[str]
    comparison_type: str
    observations: Tuple[IntelligenceObservation, ...]
    expectations: EarningsExpectations
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "comparison_type": self.comparison_type,
            "observations": [item.to_dict() for item in self.observations],
            "expectations": self.expectations.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class ValuationMetric:
    code: str
    label: str
    current_value: Optional[float]
    historical_median: Optional[float]
    premium_to_median_pct: Optional[float]
    position: str
    meaningful: bool = True
    limitations: Tuple[str, ...] = ()
    source_provider: Optional[str] = None
    data_family: Optional[str] = None
    fundamental_period_end: Optional[str] = None
    market_data_as_of: Optional[str] = None
    alignment_status: Optional[str] = None
    confidence: Optional[str] = None
    components: Tuple[Tuple[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "label": self.label,
            "current_value": self.current_value,
            "historical_median": self.historical_median,
            "premium_to_median_pct": self.premium_to_median_pct,
            "position": self.position,
            "meaningful": self.meaningful,
            "limitations": list(self.limitations),
        }
        if self.source_provider is not None:
            payload["source_provider"] = self.source_provider
        if self.data_family is not None:
            payload["data_family"] = self.data_family
        if self.fundamental_period_end is not None:
            payload["fundamental_period_end"] = self.fundamental_period_end
        if self.market_data_as_of is not None:
            payload["market_data_as_of"] = self.market_data_as_of
        if self.alignment_status is not None:
            payload["alignment_status"] = self.alignment_status
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.components:
            payload["components"] = dict(self.components)
        return payload


@dataclass(frozen=True)
class ValuationSection:
    metrics: Tuple[ValuationMetric, ...]
    observations: Tuple[IntelligenceObservation, ...]
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metrics": [item.to_dict() for item in self.metrics],
            "observations": [item.to_dict() for item in self.observations],
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class PeerComparisonRow:
    metric: str
    company_value: Optional[float]
    peer_median: Optional[float]
    difference: Optional[float]
    percentile: Optional[float]
    rank: Optional[int]
    peer_count: int
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "company_value": self.company_value,
            "peer_median": self.peer_median,
            "difference": self.difference,
            "percentile": self.percentile,
            "rank": self.rank,
            "peer_count": self.peer_count,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class PeerSection:
    peer_selection_method: str
    peer_symbols: Tuple[str, ...]
    unavailable_peers: Tuple[str, ...]
    comparisons: Tuple[PeerComparisonRow, ...]
    observations: Tuple[IntelligenceObservation, ...]
    limitations: Tuple[str, ...]
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_selection_method": self.peer_selection_method,
            "peer_symbols": list(self.peer_symbols),
            "unavailable_peers": list(self.unavailable_peers),
            "comparisons": [item.to_dict() for item in self.comparisons],
            "observations": [item.to_dict() for item in self.observations],
            "limitations": list(self.limitations),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    symbol: str
    headline: str
    source: Optional[str]
    published_at: Optional[str]
    url: Optional[str]
    summary: Optional[str]
    category: str
    materiality: str
    sentiment: Optional[str]
    impact_domains: Tuple[str, ...]
    confidence: str
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "headline": self.headline,
            "source": self.source,
            "published_at": self.published_at,
            "url": self.url,
            "summary": self.summary,
            "category": self.category,
            "materiality": self.materiality,
            "sentiment": self.sentiment,
            "impact_domains": list(self.impact_domains),
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class NewsSection:
    events: Tuple[NewsEvent, ...]
    dedupe_count: int
    provider_failures: Tuple[str, ...]
    provenance: IntelligenceProvenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [item.to_dict() for item in self.events],
            "dedupe_count": self.dedupe_count,
            "provider_failures": list(self.provider_failures),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class CatalystItem:
    code: str
    catalyst_type: str
    date: Optional[str]
    description: str
    source: str
    confidence: str
    status: str
    related_symbols: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "catalyst_type": self.catalyst_type,
            "date": self.date,
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "related_symbols": list(self.related_symbols),
        }


@dataclass(frozen=True)
class DataQualitySection:
    company_profile_available: bool
    financial_history_available: bool
    quarterly_comparison_available: bool
    earnings_expectations_available: bool
    valuation_available: bool
    historical_valuation_available: bool
    peer_data_available: bool
    news_available: bool
    catalyst_data_available: bool
    warnings: Tuple[str, ...]
    provider_failures: Tuple[str, ...]
    partial_sections: Tuple[str, ...]
    as_of: Optional[str]
    provider_diagnostic_details: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_profile_available": self.company_profile_available,
            "financial_history_available": self.financial_history_available,
            "quarterly_comparison_available": self.quarterly_comparison_available,
            "earnings_expectations_available": self.earnings_expectations_available,
            "valuation_available": self.valuation_available,
            "historical_valuation_available": self.historical_valuation_available,
            "peer_data_available": self.peer_data_available,
            "news_available": self.news_available,
            "catalyst_data_available": self.catalyst_data_available,
            "warnings": list(self.warnings),
            "provider_failures": list(self.provider_failures),
            "provider_diagnostic_details": list(self.provider_diagnostic_details),
            "partial_sections": list(self.partial_sections),
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class CompanyIntelligenceView:
    symbol: str
    company_name: Optional[str]
    as_of: Optional[str]
    business_snapshot: Optional[BusinessSnapshot]
    financial_trends: Optional[FinancialTrendsSection]
    earnings: Optional[EarningsSection]
    valuation: Optional[ValuationSection]
    peers: Optional[PeerSection]
    news: Optional[NewsSection]
    catalysts: Tuple[CatalystItem, ...] = ()
    factual_risks: Tuple[IntelligenceObservation, ...] = ()
    data_quality: Optional[DataQualitySection] = None
    provenance: Tuple[IntelligenceProvenance, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return serialize_optional(
            {
                "symbol": self.symbol,
                "company_name": self.company_name,
                "as_of": self.as_of,
                "business_snapshot": self.business_snapshot,
                "financial_trends": self.financial_trends,
                "earnings": self.earnings,
                "valuation": self.valuation,
                "peers": self.peers,
                "news": self.news,
                "catalysts": self.catalysts,
                "factual_risks": self.factual_risks,
                "data_quality": self.data_quality,
                "provenance": self.provenance,
            }
        )
