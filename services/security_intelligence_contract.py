"""Canonical Security Intelligence contract.

Architecture: raw data → facts → security intelligence → portfolio context → decision → explanation.

This module is the vocabulary only. Scoring lives in security_intelligence_engine.
NABI Score v4 remains the Scanner/candidate overall score and is not replaced here.

Security Intelligence evaluates the security in isolation.
Portfolio fit belongs on SecurityPortfolioContext, not on dimension scores.
LLM/explanation layers may narrate these facts later. They must not invent them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

ENGINE_VERSION = "security_intelligence_8a.1"
FACTS_VERSION = "security_facts_8a.1"

DIM_QUALITY = "QUALITY"
DIM_GROWTH = "GROWTH"
DIM_PROFITABILITY = "PROFITABILITY"
DIM_BALANCE_SHEET = "BALANCE_SHEET"
DIM_VALUATION = "VALUATION"
DIM_MOMENTUM = "MOMENTUM"
DIM_RISK = "RISK"
DIM_DATA_QUALITY = "DATA_QUALITY"

SECURITY_INTELLIGENCE_DIMENSIONS = (
    DIM_QUALITY,
    DIM_GROWTH,
    DIM_PROFITABILITY,
    DIM_BALANCE_SHEET,
    DIM_VALUATION,
    DIM_MOMENTUM,
    DIM_RISK,
    DIM_DATA_QUALITY,
)

STATUS_VERY_STRONG = "VERY_STRONG"
STATUS_STRONG = "STRONG"
STATUS_NEUTRAL = "NEUTRAL"
STATUS_WEAK = "WEAK"
STATUS_VERY_WEAK = "VERY_WEAK"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

DIMENSION_STATUSES = (
    STATUS_VERY_STRONG,
    STATUS_STRONG,
    STATUS_NEUTRAL,
    STATUS_WEAK,
    STATUS_VERY_WEAK,
    STATUS_INSUFFICIENT_DATA,
)

STATE_ATTRACTIVE = "ATTRACTIVE"
STATE_WATCH = "WATCH"
STATE_NEUTRAL = "NEUTRAL"
STATE_CAUTION = "CAUTION"
STATE_AVOID = "AVOID"
STATE_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

INVESTMENT_STATES = (
    STATE_ATTRACTIVE,
    STATE_WATCH,
    STATE_NEUTRAL,
    STATE_CAUTION,
    STATE_AVOID,
    STATE_INSUFFICIENT_DATA,
)

INVESTABLE_STATES = frozenset({STATE_ATTRACTIVE})

CHANGE_QUALITY_IMPROVING = "QUALITY_IMPROVING"
CHANGE_QUALITY_DETERIORATING = "QUALITY_DETERIORATING"
CHANGE_GROWTH_ACCELERATING = "GROWTH_ACCELERATING"
CHANGE_GROWTH_SLOWING = "GROWTH_SLOWING"
CHANGE_MARGIN_EXPANDING = "MARGIN_EXPANDING"
CHANGE_MARGIN_COMPRESSING = "MARGIN_COMPRESSING"
CHANGE_BALANCE_SHEET_IMPROVING = "BALANCE_SHEET_IMPROVING"
CHANGE_BALANCE_SHEET_WEAKENING = "BALANCE_SHEET_WEAKENING"
CHANGE_VALUATION_IMPROVING = "VALUATION_IMPROVING"
CHANGE_VALUATION_DETERIORATING = "VALUATION_DETERIORATING"
CHANGE_MOMENTUM_STRENGTHENING = "MOMENTUM_STRENGTHENING"
CHANGE_MOMENTUM_WEAKENING = "MOMENTUM_WEAKENING"
CHANGE_RISK_INCREASING = "RISK_INCREASING"
CHANGE_RISK_DECREASING = "RISK_DECREASING"
CHANGE_PARTICIPATION_CHANGED = "PARTICIPATION_CHANGED"
CHANGE_DATA_QUALITY_CHANGED = "DATA_QUALITY_CHANGED"

CHANGE_FLAGS = (
    CHANGE_QUALITY_IMPROVING,
    CHANGE_QUALITY_DETERIORATING,
    CHANGE_GROWTH_ACCELERATING,
    CHANGE_GROWTH_SLOWING,
    CHANGE_MARGIN_EXPANDING,
    CHANGE_MARGIN_COMPRESSING,
    CHANGE_BALANCE_SHEET_IMPROVING,
    CHANGE_BALANCE_SHEET_WEAKENING,
    CHANGE_VALUATION_IMPROVING,
    CHANGE_VALUATION_DETERIORATING,
    CHANGE_MOMENTUM_STRENGTHENING,
    CHANGE_MOMENTUM_WEAKENING,
    CHANGE_RISK_INCREASING,
    CHANGE_RISK_DECREASING,
    CHANGE_PARTICIPATION_CHANGED,
    CHANGE_DATA_QUALITY_CHANGED,
)

# Persistence is designed, not migrated in 8A.
PROPOSED_SNAPSHOT_TABLE = "security_intelligence_snapshots"


@dataclass(frozen=True)
class SecurityFacts:
    """Normalized factual inputs. Missing stays None. Never invent values."""

    symbol: str
    name: str = ""
    instrument_type: str = ""
    economic_layer: Optional[str] = None
    exchange: str = ""
    currency: str = ""
    price: Optional[float] = None
    market_cap: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    revenue: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    free_cash_flow: Optional[float] = None
    total_assets: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    equity: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    revenue_cagr_3y: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    eps_cagr_3y: Optional[float] = None
    fcf_growth_yoy: Optional[float] = None
    fcf_cagr_3y: Optional[float] = None
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_sales: Optional[float] = None
    price_to_book: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    debt_to_equity: Optional[float] = None
    net_debt: Optional[float] = None
    net_debt_to_fcf: Optional[float] = None
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    share_change_3y: Optional[float] = None
    payout_ratio: Optional[float] = None
    average_volume: Optional[float] = None
    return_1d: Optional[float] = None
    return_1w: Optional[float] = None
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_6m: Optional[float] = None
    return_1y: Optional[float] = None
    drawdown: Optional[float] = None
    volatility: Optional[float] = None
    source: str = ""
    as_of: Optional[str] = None
    stale: bool = False
    missing_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "instrument_type": self.instrument_type,
            "economic_layer": self.economic_layer,
            "exchange": self.exchange,
            "currency": self.currency,
            "price": self.price,
            "market_cap": self.market_cap,
            "high_52w": self.high_52w,
            "low_52w": self.low_52w,
            "revenue": self.revenue,
            "operating_income": self.operating_income,
            "net_income": self.net_income,
            "eps": self.eps,
            "free_cash_flow": self.free_cash_flow,
            "total_assets": self.total_assets,
            "total_debt": self.total_debt,
            "cash": self.cash,
            "equity": self.equity,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "net_margin": self.net_margin,
            "fcf_margin": self.fcf_margin,
            "roe": self.roe,
            "roa": self.roa,
            "roic": self.roic,
            "revenue_growth_yoy": self.revenue_growth_yoy,
            "revenue_cagr_3y": self.revenue_cagr_3y,
            "eps_growth_yoy": self.eps_growth_yoy,
            "eps_cagr_3y": self.eps_cagr_3y,
            "fcf_growth_yoy": self.fcf_growth_yoy,
            "fcf_cagr_3y": self.fcf_cagr_3y,
            "pe": self.pe,
            "forward_pe": self.forward_pe,
            "price_to_sales": self.price_to_sales,
            "price_to_book": self.price_to_book,
            "ev_ebitda": self.ev_ebitda,
            "fcf_yield": self.fcf_yield,
            "debt_to_equity": self.debt_to_equity,
            "net_debt": self.net_debt,
            "net_debt_to_fcf": self.net_debt_to_fcf,
            "current_ratio": self.current_ratio,
            "interest_coverage": self.interest_coverage,
            "share_change_3y": self.share_change_3y,
            "payout_ratio": self.payout_ratio,
            "average_volume": self.average_volume,
            "return_1d": self.return_1d,
            "return_1w": self.return_1w,
            "return_1m": self.return_1m,
            "return_3m": self.return_3m,
            "return_6m": self.return_6m,
            "return_1y": self.return_1y,
            "drawdown": self.drawdown,
            "volatility": self.volatility,
            "source": self.source,
            "as_of": self.as_of,
            "stale": self.stale,
            "missing_fields": list(self.missing_fields),
        }


@dataclass(frozen=True)
class SecurityParticipationContext:
    status: str = ""
    research_allowed: Optional[bool] = None
    methodology: str = ""
    as_of: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "research_allowed": self.research_allowed,
            "methodology": self.methodology,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class SecurityPortfolioContext:
    """Portfolio suitability inputs. Not used by Security Intelligence scoring."""

    is_held: bool = False
    position_value: Optional[float] = None
    portfolio_weight: Optional[float] = None
    economic_layer: Optional[str] = None
    layer_status: str = ""
    sector_weight: Optional[float] = None
    concentration: Optional[float] = None
    existing_gain_loss: Optional[float] = None
    goal_context: str = ""
    new_money_eligibility: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_held": self.is_held,
            "position_value": self.position_value,
            "portfolio_weight": self.portfolio_weight,
            "economic_layer": self.economic_layer,
            "layer_status": self.layer_status,
            "sector_weight": self.sector_weight,
            "concentration": self.concentration,
            "existing_gain_loss": self.existing_gain_loss,
            "goal_context": self.goal_context,
            "new_money_eligibility": self.new_money_eligibility,
        }


@dataclass(frozen=True)
class DimensionResult:
    name: str
    score: Optional[float]
    status: str
    confidence: float
    facts_used: tuple[str, ...]
    missing_facts: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "status": self.status,
            "confidence": self.confidence,
            "facts_used": list(self.facts_used),
            "missing_facts": list(self.missing_facts),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class SecurityIntelligenceView:
    symbol: str
    quality: DimensionResult
    growth: DimensionResult
    profitability: DimensionResult
    balance_sheet: DimensionResult
    valuation: DimensionResult
    momentum: DimensionResult
    risk: DimensionResult
    data_quality: DimensionResult
    overall_score: Optional[float]
    overall_status: str
    overall_confidence: float
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    risk_flags: tuple[str, ...]
    change_flags: tuple[str, ...]
    participation_status: str
    research_allowed: Optional[bool]
    investment_state: str
    investable: bool
    engine_version: str = ENGINE_VERSION
    facts_version: str = FACTS_VERSION

    def dimension(self, name: str) -> DimensionResult:
        mapping = {
            DIM_QUALITY: self.quality,
            DIM_GROWTH: self.growth,
            DIM_PROFITABILITY: self.profitability,
            DIM_BALANCE_SHEET: self.balance_sheet,
            DIM_VALUATION: self.valuation,
            DIM_MOMENTUM: self.momentum,
            DIM_RISK: self.risk,
            DIM_DATA_QUALITY: self.data_quality,
        }
        return mapping[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quality": self.quality.to_dict(),
            "growth": self.growth.to_dict(),
            "profitability": self.profitability.to_dict(),
            "balance_sheet": self.balance_sheet.to_dict(),
            "valuation": self.valuation.to_dict(),
            "momentum": self.momentum.to_dict(),
            "risk": self.risk.to_dict(),
            "data_quality": self.data_quality.to_dict(),
            "overall_score": self.overall_score,
            "overall_status": self.overall_status,
            "overall_confidence": self.overall_confidence,
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "risk_flags": list(self.risk_flags),
            "change_flags": list(self.change_flags),
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "investment_state": self.investment_state,
            "investable": self.investable,
            "engine_version": self.engine_version,
            "facts_version": self.facts_version,
        }


@dataclass(frozen=True)
class SecurityIntelligenceSnapshot:
    symbol: str
    as_of: Optional[str]
    engine_version: str
    facts_version: str
    overall_score: Optional[float]
    overall_status: str
    investment_state: str
    participation_status: str
    research_allowed: Optional[bool]
    dimension_scores: dict[str, Optional[float]] = field(default_factory=dict)
    dimension_statuses: dict[str, str] = field(default_factory=dict)
    change_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "engine_version": self.engine_version,
            "facts_version": self.facts_version,
            "overall_score": self.overall_score,
            "overall_status": self.overall_status,
            "investment_state": self.investment_state,
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "dimension_scores": dict(self.dimension_scores),
            "dimension_statuses": dict(self.dimension_statuses),
            "change_flags": list(self.change_flags),
        }


def snapshot_from_view(
    view: SecurityIntelligenceView,
    *,
    as_of: Optional[str] = None,
) -> SecurityIntelligenceSnapshot:
    return SecurityIntelligenceSnapshot(
        symbol=view.symbol,
        as_of=as_of,
        engine_version=view.engine_version,
        facts_version=view.facts_version,
        overall_score=view.overall_score,
        overall_status=view.overall_status,
        investment_state=view.investment_state,
        participation_status=view.participation_status,
        research_allowed=view.research_allowed,
        dimension_scores={
            name: view.dimension(name).score for name in SECURITY_INTELLIGENCE_DIMENSIONS
        },
        dimension_statuses={
            name: view.dimension(name).status for name in SECURITY_INTELLIGENCE_DIMENSIONS
        },
        change_flags=view.change_flags,
    )


def proposed_snapshot_schema() -> dict[str, str]:
    """Design-only. No production migration in 8A."""
    return {
        "table": PROPOSED_SNAPSHOT_TABLE,
        "id": "uuid",
        "symbol": "text",
        "as_of": "timestamptz",
        "facts_version": "text",
        "engine_version": "text",
        "dimension_scores": "jsonb",
        "dimension_statuses": "jsonb",
        "overall_score": "numeric",
        "overall_status": "text",
        "overall_confidence": "numeric",
        "investment_state": "text",
        "participation_status": "text",
        "research_allowed": "boolean",
        "change_flags": "jsonb",
        "created_at": "timestamptz",
    }
