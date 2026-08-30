"""Generic Fund/ETF product contracts.

Provider-agnostic so SP Funds and later TEFAS/KAP share one intelligence path.
Does not score equity Security Intelligence and does not emit Participation Uygun.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Optional, Protocol

from services.security_identity_contract import ECONOMIC_LAYERS
from services.wealth_asset_classification import KNOWN_ETF_SYMBOLS

PROVIDER_SP_FUNDS_OFFICIAL = "sp_funds_official"
PROVIDER_TEFAS = "tefas"
PROVIDER_KAP_FUND = "kap_fund"
PROVIDER_FUND_MANAGER = "official_fund_manager"

FUND_PRODUCT_PROVIDERS = (
    PROVIDER_SP_FUNDS_OFFICIAL,
    PROVIDER_TEFAS,
    PROVIDER_KAP_FUND,
    PROVIDER_FUND_MANAGER,
)

PILOT_FUND_SYMBOLS = ("SPUS", "SPSK", "SPRE", "SPWO")
assert set(PILOT_FUND_SYMBOLS).issubset(KNOWN_ETF_SYMBOLS)

FUND_TYPE_ETF = "etf"
FUND_TYPE_MUTUAL = "mutual_fund"

READINESS_READY_NOW = "READY_NOW"
READINESS_NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
READINESS_NOT_APPLICABLE = "NOT_APPLICABLE"
READINESS_STATES = (
    READINESS_READY_NOW,
    READINESS_NEEDS_MORE_DATA,
    READINESS_NOT_APPLICABLE,
)

DIM_PARTICIPATION = "participation_mandate"
DIM_PERFORMANCE = "performance_momentum"
DIM_RISK = "risk_drawdown"
DIM_COST = "cost"
DIM_DIVERSIFICATION = "diversification"
DIM_CONCENTRATION = "concentration"
DIM_TRACKING = "tracking_quality"
DIM_LIQUIDITY = "liquidity"
DIM_PORTFOLIO_FIT = "portfolio_fit"
DIM_DURATION_YIELD = "duration_yield_credit"
DIM_REAL_ESTATE_RISK = "real_estate_risk"
DIM_COUNTRY_CURRENCY = "country_currency"

FUND_INTELLIGENCE_DIMENSIONS = (
    DIM_PARTICIPATION,
    DIM_PERFORMANCE,
    DIM_RISK,
    DIM_COST,
    DIM_DIVERSIFICATION,
    DIM_CONCENTRATION,
    DIM_TRACKING,
    DIM_LIQUIDITY,
    DIM_PORTFOLIO_FIT,
    DIM_DURATION_YIELD,
    DIM_REAL_ESTATE_RISK,
    DIM_COUNTRY_CURRENCY,
)

REGION_US = "US"
REGION_INTERNATIONAL_EX_US = "INTERNATIONAL_EX_US"
REGION_GLOBAL = "GLOBAL"
REGION_UNKNOWN = "UNKNOWN"

MARKET_US = "US"
MARKET_OTHER = "other"

CASH_TICKERS = frozenset({"CASH&OTHER", "CASH", "OTHER"})


@dataclass(frozen=True)
class OfficialEvidenceRef:
    source: str
    source_url: str
    as_of: Optional[str] = None
    document_title: Optional[str] = None
    excerpt: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundIdentity:
    symbol: str
    official_name: Optional[str]
    instrument_type: str
    fund_type: str
    issuer_family: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    cusip: Optional[str]
    security_master_status: str
    source: str
    source_url: str
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundFacts:
    symbol: str
    official_name: Optional[str] = None
    fund_type: str = FUND_TYPE_ETF
    asset_class: Optional[str] = None
    strategy: Optional[str] = None
    benchmark: Optional[str] = None
    nav: Optional[float] = None
    market_price: Optional[float] = None
    net_assets: Optional[float] = None
    expense_ratio: Optional[float] = None
    inception_date: Optional[str] = None
    latest_distribution: Optional[str] = None
    holdings_as_of: Optional[str] = None
    holdings_count: Optional[int] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    cusip: Optional[str] = None
    sharia_methodology: Optional[str] = None
    source: str = ""
    source_url: str = ""
    as_of: Optional[str] = None
    limitations: tuple[str, ...] = ()
    raw_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficialFundMandate:
    """Fund-level economic role from official mandate text. Not a holding classifier."""

    symbol: str
    primary_layer: str
    region: str
    vehicle: Optional[str]
    confidence: str
    source: str
    source_url: str
    evidence_excerpt: str
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.primary_layer not in ECONOMIC_LAYERS:
            raise ValueError(f"mandate layer must be a canonical economic layer: {self.primary_layer}")


@dataclass(frozen=True)
class FundShariaEvidence:
    symbol: str
    official_mandate_present: bool
    official_certificate_listed: bool
    official_auditor_report_listed: bool
    methodology: Optional[str]
    auditor: Optional[str]
    benchmark_sharia: bool
    source: str
    source_url: str
    evidence_as_of: Optional[str]
    excerpts: tuple[str, ...]
    confidence: str
    eligibility_ready: str
    participation_status: Optional[str] = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PurificationFactor:
    symbol: str
    period: str
    factor_pct: Optional[float]
    source: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundPurificationEvidence:
    symbol: str
    purification_required: Optional[bool]
    latest_factor_pct: Optional[float]
    factor_period: Optional[str]
    source: str
    source_url: str
    as_of: Optional[str]
    methodology: Optional[str]
    factors: tuple[PurificationFactor, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HoldingsChangeSet:
    fund_symbol: str
    previous_as_of: Optional[str]
    current_as_of: Optional[str]
    new_holdings_date: bool
    added: tuple[str, ...]
    removed: tuple[str, ...]
    weight_changed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LookthroughHolding:
    holding_identifier: str
    security_name: Optional[str]
    weight_pct: float
    resolved: bool
    cash_or_other: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundLookthroughSummary:
    fund_symbol: str
    as_of: Optional[str]
    holdings_count: int
    top_holding: Optional[LookthroughHolding]
    top_holding_weight_pct: Optional[float]
    top10_weight_pct: float
    single_name_concentration_pct: Optional[float]
    cash_other_weight_pct: float
    unknown_weight_pct: float
    sector_allocation: tuple[tuple[str, float], ...]
    country_allocation: tuple[tuple[str, float], ...]
    known_nabi_overlap: tuple[str, ...]
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.top_holding is not None:
            payload["top_holding"] = self.top_holding.to_dict()
        return payload


@dataclass(frozen=True)
class OverlapRow:
    underlying_symbol: str
    direct_weight_pct: float
    lookthrough_weight_pct: float
    combined_weight_pct: float
    source_funds: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioFundOverlapView:
    direct_symbols: tuple[str, ...]
    indirect_symbols: tuple[str, ...]
    rows: tuple[OverlapRow, ...]
    largest_combined: tuple[OverlapRow, ...]
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [row.to_dict() for row in self.rows]
        payload["largest_combined"] = [row.to_dict() for row in self.largest_combined]
        return payload


@dataclass(frozen=True)
class DimensionReadiness:
    dimension: str
    state: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundIntelligenceReadiness:
    symbol: str
    dimensions: tuple[DimensionReadiness, ...]
    invented_score: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dimensions"] = [item.to_dict() for item in self.dimensions]
        return payload


DIM_STATUS_READY = "READY"
DIM_STATUS_MISSING = "MISSING"
DIM_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
FUND_DIMENSION_STATUSES = (DIM_STATUS_READY, DIM_STATUS_MISSING, DIM_STATUS_NOT_APPLICABLE)

PROFILE_EQUITY_ETF = "EQUITY_ETF"
PROFILE_SUKUK_ETF = "SUKUK_ETF"
PROFILE_REIT_ETF = "REIT_ETF"

DIM_PARTICIPATION_MANDATE = "PARTICIPATION_MANDATE"
DIM_PERFORMANCE_EVAL = "PERFORMANCE"
DIM_MOMENTUM_EVAL = "MOMENTUM"
DIM_RISK_EVAL = "RISK"
DIM_COST_EVAL = "COST"
DIM_DIVERSIFICATION_EVAL = "DIVERSIFICATION"
DIM_CONCENTRATION_EVAL = "CONCENTRATION"
DIM_LIQUIDITY_EVAL = "LIQUIDITY"
DIM_TRACKING_EVAL = "TRACKING"
DIM_PORTFOLIO_FIT_EVAL = "PORTFOLIO_FIT"
DIM_DURATION = "DURATION"
DIM_YIELD = "YIELD"
DIM_CREDIT_QUALITY = "CREDIT_QUALITY"
DIM_ISSUER_CONCENTRATION = "ISSUER_CONCENTRATION"
DIM_REAL_ESTATE_CONCENTRATION = "REAL_ESTATE_CONCENTRATION"
DIM_COUNTRY_CONCENTRATION = "COUNTRY_CONCENTRATION"
DIM_CURRENCY_EXPOSURE = "CURRENCY_EXPOSURE"

FUND_EVAL_ENGINE_VERSION = "fund_intelligence_1c.1"
FUND_EVAL_FACTS_VERSION = "fund_facts_1a.1"

# Documented weights. Missing READY dimensions are excluded, never redistributed.
EQUITY_ETF_WEIGHTS = {
    DIM_PERFORMANCE_EVAL: 0.20,
    DIM_MOMENTUM_EVAL: 0.10,
    DIM_RISK_EVAL: 0.15,
    DIM_COST_EVAL: 0.15,
    DIM_DIVERSIFICATION_EVAL: 0.15,
    DIM_CONCENTRATION_EVAL: 0.15,
    DIM_LIQUIDITY_EVAL: 0.10,
    DIM_TRACKING_EVAL: 0.10,
    DIM_COUNTRY_CONCENTRATION: 0.10,
    DIM_CURRENCY_EXPOSURE: 0.05,
}
SUKUK_ETF_WEIGHTS = {
    DIM_PERFORMANCE_EVAL: 0.10,
    DIM_RISK_EVAL: 0.10,
    DIM_COST_EVAL: 0.10,
    DIM_DIVERSIFICATION_EVAL: 0.10,
    DIM_CONCENTRATION_EVAL: 0.10,
    DIM_LIQUIDITY_EVAL: 0.10,
    DIM_DURATION: 0.15,
    DIM_YIELD: 0.15,
    DIM_CREDIT_QUALITY: 0.15,
    DIM_ISSUER_CONCENTRATION: 0.15,
}
REIT_ETF_WEIGHTS = {
    DIM_PERFORMANCE_EVAL: 0.15,
    DIM_MOMENTUM_EVAL: 0.10,
    DIM_RISK_EVAL: 0.15,
    DIM_COST_EVAL: 0.10,
    DIM_DIVERSIFICATION_EVAL: 0.10,
    DIM_CONCENTRATION_EVAL: 0.15,
    DIM_LIQUIDITY_EVAL: 0.10,
    DIM_REAL_ESTATE_CONCENTRATION: 0.15,
}

MIN_READY_SCORED_DIMENSIONS = 4
MIN_READY_WEIGHT_COVERAGE = 0.55
RETURN_RISK_FAMILY = frozenset(
    {DIM_PERFORMANCE_EVAL, DIM_RISK_EVAL, DIM_DURATION, DIM_YIELD}
)


@dataclass(frozen=True)
class FundDimensionResult:
    name: str
    status: str
    score: Optional[float] = None
    confidence: float = 0.0
    facts_used: tuple[str, ...] = ()
    missing_facts: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundParticipationGate:
    eligible: bool
    status: str
    official_mandate_present: bool
    official_certificate_listed: bool
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficialFundPerformance:
    """Official/free historical series only. Absence stays None. Never synthesized."""

    symbol: str
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_1y: Optional[float] = None
    drawdown: Optional[float] = None
    volatility: Optional[float] = None
    source: str = ""
    as_of: Optional[str] = None

    def has_return_history(self) -> bool:
        return any(value is not None for value in (self.return_1m, self.return_3m, self.return_1y))

    def has_risk_history(self) -> bool:
        return self.drawdown is not None or self.volatility is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundIntelligenceEvaluation:
    """Intrinsic fund assessment. Portfolio fit and sizing live elsewhere."""

    symbol: str
    fund_type_profile: str
    state: str
    score: Optional[float]
    confidence: float
    as_of: Optional[str]
    facts_version: str
    engine_version: str
    provenance: tuple[str, ...]
    dimensions: tuple[FundDimensionResult, ...]
    participation: FundParticipationGate
    missing_evidence: tuple[str, ...]
    publishable: bool
    purification_factor_pct: Optional[float] = None
    purification_required: Optional[bool] = None

    def dimension(self, name: str) -> Optional[FundDimensionResult]:
        for row in self.dimensions:
            if row.name == name:
                return row
        return None

    def evidence_map(self) -> dict[str, str]:
        return {row.name: row.status for row in self.dimensions}

    def generic_intelligence(self) -> dict[str, Any]:
        """8E consumes Fund Intelligence through the same SI state fields."""
        return {
            "si_state": self.state,
            "si_score": self.score,
            "si_confidence": self.confidence,
            "si_data_quality": "INSUFFICIENT" if self.state == "INSUFFICIENT_DATA" else "FUND",
            "si_as_of": self.as_of,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dimensions"] = [row.to_dict() for row in self.dimensions]
        payload["participation"] = self.participation.to_dict()
        return payload


class FundProductProvider(Protocol):
    """Official product provider. TEFAS later implements the same surface."""

    provider_id: str

    def supports(self, symbol: str) -> bool: ...

    def identity(self, symbol: str) -> FundIdentity: ...

    def facts(self, symbol: str) -> FundFacts: ...

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence: ...

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence: ...
