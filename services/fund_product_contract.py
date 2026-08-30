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
    known_weight_pct: float = 0.0
    top5_weight_pct: float = 0.0
    raw_weight_sum_pct: float = 0.0
    rounding_difference_pct: float = 0.0
    weight_reconciled: bool = True
    hhi: Optional[float] = None
    effective_holdings: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.top_holding is not None:
            payload["top_holding"] = self.top_holding.to_dict()
        return payload


@dataclass(frozen=True)
class FundHoldingsIntelligenceEvidence:
    """Derived official-weight facts only. No sector/country/currency invention."""

    fund_symbol: str
    as_of: Optional[str]
    holding_count: int
    known_weight: float
    unknown_weight: float
    largest_holding_weight: Optional[float]
    top_5_weight: float
    top_10_weight: float
    effective_number_of_holdings: Optional[float]
    hhi: Optional[float]
    cash_other_weight: float
    raw_weight_sum: float
    rounding_difference: float
    weight_reconciled: bool
    source: str
    provenance: tuple[str, ...]
    official_issuer_field_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NportTenorRisk:
    """SEC N-PORT tenor bucket. Values are official portfolio value changes."""

    period: str
    value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NportDebtHolding:
    """Official N-PORT security row. name is the SEC issuer field, not a guessed label."""

    issuer_name: str
    lei: Optional[str]
    title: str
    cusip: Optional[str]
    isin: Optional[str]
    maturity_date: Optional[str]
    weight_pct: float
    value_usd: Optional[float]
    currency: Optional[str]
    issuer_category: Optional[str]
    asset_category: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundFixedIncomeRiskEvidence:
    """Official fixed-income facts only. DV01 is not duration. Spread is not a rating."""

    fund_symbol: str
    as_of: Optional[str]
    period_ended: Optional[str]
    interest_rate_risk_dv01: tuple[NportTenorRisk, ...]
    interest_rate_risk_dv100: tuple[NportTenorRisk, ...]
    credit_spread_risk_ig: tuple[NportTenorRisk, ...]
    credit_spread_risk_non_ig: tuple[NportTenorRisk, ...]
    holdings: tuple[NportDebtHolding, ...]
    holding_count: int
    dated_weight_pct: float
    residual_weight_pct: float
    unknown_maturity_weight_pct: float
    weighted_average_maturity_years: Optional[float]
    duration: Optional[float]
    credit_quality: Optional[str]
    official_issuer_field: str
    official_issuer_field_present: bool
    unknown_issuer_weight_pct: float
    largest_issuer_weight: Optional[float]
    top10_issuer_weight: Optional[float]
    issuer_count: int
    currency_weights: tuple[tuple[str, float], ...]
    source: str
    source_url: str
    provenance: tuple[str, ...]
    reliability: str
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def rate_risk_present(self) -> bool:
        return bool(self.interest_rate_risk_dv01 or self.interest_rate_risk_dv100)

    @property
    def credit_spread_present(self) -> bool:
        return bool(self.credit_spread_risk_ig or self.credit_spread_risk_non_ig)

    @property
    def issuer_reliable(self) -> bool:
        return (
            self.official_issuer_field_present
            and self.unknown_issuer_weight_pct <= 10.0
            and self.largest_issuer_weight is not None
        )


@dataclass(frozen=True)
class FundExposureEvidence:
    """Official N-PORT country/currency facts only. No ticker or name inference."""

    fund_symbol: str
    as_of: Optional[str]
    country_weights: tuple[tuple[str, float], ...]
    currency_weights: tuple[tuple[str, float], ...]
    sector_weights: tuple[tuple[str, float], ...]
    property_type_weights: tuple[tuple[str, float], ...]
    developed_emerging_weights: tuple[tuple[str, float], ...]
    known_country_weight: float
    unknown_country_weight: float
    known_currency_weight: float
    unknown_currency_weight: float
    holding_count: int
    raw_weight_sum: float
    residual_weight: float
    largest_country: Optional[str]
    largest_country_weight: Optional[float]
    top5_country_weight: Optional[float]
    country_count: int
    currency_semantics: str
    source: str
    source_url: str
    provenance: tuple[str, ...]
    reliability: str
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def country_reliable(self) -> bool:
        return (
            self.country_count > 0
            and self.unknown_country_weight <= 10.0
            and self.largest_country_weight is not None
        )

    @property
    def denomination_present(self) -> bool:
        return bool(self.currency_weights) and self.unknown_currency_weight <= 10.0


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
DIM_RATE_RISK = "RATE_RISK"
DIM_CREDIT_RISK = "CREDIT_RISK"
DIM_CURRENCY_DENOMINATION = "CURRENCY_DENOMINATION"
DIM_DEVELOPED_EMERGING = "DEVELOPED_EMERGING"

FUND_EVAL_ENGINE_VERSION = "fund_intelligence_1g.1"
FUND_EVAL_FACTS_VERSION = "fund_facts_1d.1"
PERFORMANCE_BASIS_NAV = "NAV"
PERFORMANCE_BASIS_MARKET_PRICE = "MARKET_PRICE"
TRACKING_CONCEPT_DIFFERENCE = "TRACKING_DIFFERENCE"
YIELD_BASIS_SEC_30D = "SEC_30_DAY_YIELD"
PERFORMANCE_LEAD_HORIZONS = ("return_1y", "return_3y", "return_5y", "since_inception_annualized")
MOMENTUM_LEAD_HORIZONS = ("return_3m", "return_6m", "return_ytd", "return_1m")

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
class OfficialFundYield:
    """Official yield metadata. Never treated as total return."""

    symbol: str
    sec_yield_30d: Optional[float] = None
    as_of: Optional[str] = None
    source: str = ""
    source_url: str = ""
    basis: str = YIELD_BASIS_SEC_30D

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficialNportSnapshot:
    """Pilot N-PORT period snapshot. No daily NAV series. No crawler."""

    symbol: str
    cik: str
    series_id: str
    class_id: str
    registrant: str
    period_of_report: Optional[str]
    accession: str
    source_url: str
    tot_assets: Optional[float] = None
    net_assets: Optional[float] = None
    shares_outstanding: Optional[float] = None
    nav_per_share: Optional[float] = None
    nav_method: str = ""
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficialFundPerformance:
    """Official/free standardized performance. Absence stays None. Never synthesized."""

    symbol: str
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_1y: Optional[float] = None
    drawdown: Optional[float] = None
    volatility: Optional[float] = None
    source: str = ""
    as_of: Optional[str] = None
    fund_symbol: str = ""
    basis: str = PERFORMANCE_BASIS_NAV
    return_6m: Optional[float] = None
    return_ytd: Optional[float] = None
    return_3y: Optional[float] = None
    return_5y: Optional[float] = None
    since_inception_cumulative: Optional[float] = None
    since_inception_annualized: Optional[float] = None
    benchmark_name: Optional[str] = None
    benchmark_ticker: Optional[str] = None
    benchmark_return_1m: Optional[float] = None
    benchmark_return_3m: Optional[float] = None
    benchmark_return_6m: Optional[float] = None
    benchmark_return_ytd: Optional[float] = None
    benchmark_return_1y: Optional[float] = None
    benchmark_return_3y: Optional[float] = None
    benchmark_return_5y: Optional[float] = None
    tracking_difference: Optional[float] = None
    tracking_horizon: Optional[str] = None
    tracking_concept: str = TRACKING_CONCEPT_DIFFERENCE
    source_url: str = ""
    provenance: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def resolved_symbol(self) -> str:
        return self.fund_symbol or self.symbol

    def has_return_history(self) -> bool:
        return any(
            value is not None
            for value in (
                self.return_1m,
                self.return_3m,
                self.return_6m,
                self.return_ytd,
                self.return_1y,
                self.return_3y,
                self.return_5y,
                self.since_inception_annualized,
            )
        )

    def has_risk_history(self) -> bool:
        return self.drawdown is not None or self.volatility is not None

    def performance_lead(self) -> tuple[Optional[float], Optional[str]]:
        for name in PERFORMANCE_LEAD_HORIZONS:
            value = getattr(self, name)
            if value is not None:
                return value, name
        return None, None

    def momentum_lead(self) -> tuple[Optional[float], Optional[str]]:
        for name in MOMENTUM_LEAD_HORIZONS:
            value = getattr(self, name)
            if value is not None:
                return value, name
        return None, None

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


PILOT_TEFAS_FUND_CODES = ("AIS", "ZPE", "IAT")

IDENTITY_RESOLVED = "RESOLVED"
IDENTITY_UNRESOLVED = "UNRESOLVED"
TURKIYE_IDENTITY_STATES = (IDENTITY_RESOLVED, IDENTITY_UNRESOLVED)

PROFILE_SHORT_TERM_PARTICIPATION = "short_term_liquidity_participation"
PROFILE_PARTICIPATION_EQUITY = "participation_equity"
PROFILE_SUKUK_LEASE_CERTIFICATE = "sukuk_lease_certificate_participation"

TEFAS_PRICE_FIELD = "fiyat"
TEFAS_PRICE_SEMANTICS = "TEFAS_UNIT_PRICE"
TEFAS_ENDPOINT_SNAPSHOT = "/api/funds/fonBilgiGetir"
TEFAS_ENDPOINT_RETURNS = "/api/funds/fonGetiriBazliBilgiGetir"
TEFAS_ENDPOINT_PRICES = "/api/funds/fonFiyatBilgiGetir"

PDR_FIELD_ASSET_WEIGHTS = "Aylık Ortalama Portföydeki Menkul Kıymetler Yüzdesi"
PDR_FIELD_HOLDINGS = "III-FON PORTFÖY DEĞERİ TABLOSU"
PDR_FIELD_ISSUER = "İHRAÇCI KURUM"
PDR_FIELD_ISIN = "ISIN KODU"
PDR_FIELD_MATURITY = "VADE TARİHİ"
PDR_FIELD_CURRENCY = "DÖVİZ CİNSİ"


@dataclass(frozen=True)
class TurkiyeFundIdentity:
    fund_code: str
    official_name: Optional[str]
    fund_type: Optional[str]
    currency: Optional[str]
    founder: Optional[str]
    portfolio_manager: Optional[str]
    tefas_source: str
    tefas_source_url: str
    kap_source: str
    kap_source_url: str
    identity_status: str
    as_of: Optional[str]
    isin: Optional[str] = None
    umbrella_type: Optional[str] = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TefasPriceObservation:
    date: str
    price: float
    fund_code: str
    official_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TefasPriceSeries:
    fund_code: str
    first_date: Optional[str]
    last_date: Optional[str]
    observation_count: int
    duplicate_dates: tuple[str, ...]
    missing_dates: tuple[str, ...]
    weekday_gaps: tuple[str, ...]
    price_field: str
    price_semantics: str
    source: str
    source_url: str
    period_months: Optional[int] = None
    observations: tuple[TefasPriceObservation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observations"] = [row.to_dict() if hasattr(row, "to_dict") else row for row in self.observations]
        return payload


@dataclass(frozen=True)
class KapFundMandateEvidence:
    fund_code: str
    official_name: Optional[str]
    umbrella_name: Optional[str]
    umbrella_type: Optional[str]
    founder: Optional[str]
    portfolio_manager: Optional[str]
    strategy_text: Optional[str]
    participation_wording: tuple[str, ...]
    allowed_asset_classes: tuple[str, ...]
    currency_restriction: Optional[str]
    maturity_restriction: Optional[str]
    minimum_equity_allocation: Optional[str]
    sukuk_mandate: Optional[str]
    benchmark: Optional[str]
    management_fee_annual_pct: Optional[float]
    official_profile: Optional[str]
    source: str
    source_url: str
    as_of: Optional[str]
    excerpts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KapPortfolioReportAudit:
    fund_code: str
    latest_report_title: Optional[str]
    latest_report_url: Optional[str]
    period: Optional[str]
    asset_weights: bool
    holdings: bool
    issuer: bool
    maturity: bool
    currency: bool
    country: bool
    lookthrough: bool
    exact_fields: tuple[str, ...]
    source: str
    source_url: str
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FundProductProvider(Protocol):
    """Official product provider. TEFAS later implements the same surface."""

    provider_id: str

    def supports(self, symbol: str) -> bool: ...

    def identity(self, symbol: str) -> FundIdentity: ...

    def facts(self, symbol: str) -> FundFacts: ...

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence: ...

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence: ...
