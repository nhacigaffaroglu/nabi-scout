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


class FundProductProvider(Protocol):
    """Official product provider. TEFAS later implements the same surface."""

    provider_id: str

    def supports(self, symbol: str) -> bool: ...

    def identity(self, symbol: str) -> FundIdentity: ...

    def facts(self, symbol: str) -> FundFacts: ...

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence: ...

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence: ...
