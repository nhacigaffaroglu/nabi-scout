from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from services.participation_intelligence_contract import ParticipationAssessment

ANALYSIS_KIND_FUND = "fund"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

PARTICIPATION_SOURCE_CONFIGURED = "configured"

DATA_PROVIDER_ALPHA_VANTAGE = "Alpha Vantage"

DIMENSION_COST = "Maliyet"
DIMENSION_LIQUIDITY = "Likidite"
DIMENSION_CONCENTRATION = "Yoğunlaşma"
DIMENSION_DATA_QUALITY = "Veri kalitesi"

LABEL_INCELEME_UYGUN = "İncelemeye uygun"
LABEL_VERI_YETERSIZ = "Veri yetersiz"
LABEL_YUKSEK_MALIYET = "Yüksek maliyet"
LABEL_YOGUNLASMA_RISKI = "Yoğunlaşma riski"
LABEL_CONFIGURED_PARTICIPATION = "Yapılandırılmış katılım ETF'si"

LABEL_VOLATILITY_LOW = "Düşük oynaklık"
LABEL_VOLATILITY_MODERATE = "Orta oynaklık"
LABEL_VOLATILITY_HIGH = "Yüksek oynaklık"
LABEL_DRAWDOWN_LIMITED = "Sınırlı düşüş"
LABEL_DRAWDOWN_MODERATE = "Orta düşüş"
LABEL_DRAWDOWN_DEEP = "Derin düşüş"

PERFORMANCE_SECTION_TITLE = "Performans (fiyat bazlı)"
RISK_SECTION_TITLE = "Risk (fiyat bazlı)"
PRICE_RETURN_DISCLAIMER = "Temettü/dağıtım etkisi dahil değildir."
BENCHMARK_RELATIVE_DISCLAIMER = "Göreli benchmark analizi henüz yok."
PERFORMANCE_UNAVAILABLE_MESSAGE = (
    "Fiyat geçmişi mevcut olmadığı için performans/risk metrikleri hesaplanamadı."
)
RETURN_1Y_INSUFFICIENT_MESSAGE = "1 yıllık getiri için yeterli fiyat geçmişi yok."

STALE_OBSERVATION_WARNING = "Son fiyat verisi güncel olmayabilir."


def history_coverage_caption(observation_count: int) -> str:
    return (
        "Performans metrikleri mevcut fiyat geçmişine göre hesaplanmıştır "
        f"({observation_count} gözlem)."
    )


@dataclass(frozen=True)
class PricePoint:
    date: date
    close: float
    volume: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    points: Tuple[PricePoint, ...] = field(default_factory=tuple)
    source: str = "unknown"
    last_observation_date: Optional[date] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "last_observation_date": (
                self.last_observation_date.isoformat()
                if self.last_observation_date
                else None
            ),
            "points": [point.to_dict() for point in self.points],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class FundPerformanceMetrics:
    return_1m_pct: Optional[float] = None
    return_ytd_pct: Optional[float] = None
    return_1y_pct: Optional[float] = None
    observation_count: int = 0
    is_stale: bool = False
    return_1y_full_confidence: Optional[bool] = None
    history_start_date: Optional[str] = None
    history_end_date: Optional[str] = None
    history_is_full_year: bool = False
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def has_any_return(self) -> bool:
        return any(
            value is not None
            for value in (
                self.return_1m_pct,
                self.return_ytd_pct,
                self.return_1y_pct,
            )
        )


@dataclass(frozen=True)
class FundRiskMetrics:
    annualized_volatility_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    volatility_label: Optional[str] = None
    drawdown_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def has_any_metric(self) -> bool:
        return (
            self.annualized_volatility_pct is not None
            or self.max_drawdown_pct is not None
        )


@dataclass(frozen=True)
class FundHolding:
    symbol: Optional[str]
    name: Optional[str]
    weight_pct: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundDimensionScore:
    dimension: str
    score: float
    observation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundAnalysisResult:
    symbol: str
    analysis_kind: str = ANALYSIS_KIND_FUND
    fund_name: Optional[str] = None
    issuer: Optional[str] = None
    exchange: Optional[str] = None
    asset_class: Optional[str] = None
    domicile: Optional[str] = None
    benchmark: Optional[str] = None
    inception_date: Optional[str] = None
    holdings_count: Optional[int] = None
    top_holdings: List[FundHolding] = field(default_factory=list)
    top10_concentration_pct: Optional[float] = None
    sector_weights: Optional[Dict[str, float]] = None
    country_weights: Optional[Dict[str, float]] = None
    expense_ratio: Optional[float] = None
    distribution_yield: Optional[float] = None
    aum: Optional[float] = None
    current_price: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    participation_status: Optional[str] = None
    participation_score: Optional[int] = None
    participation_source: Optional[str] = None
    participation_assessment: Optional[ParticipationAssessment] = None
    data_completeness_pct: float = 0.0
    analysis_confidence: str = CONFIDENCE_LOW
    data_provider: Optional[str] = None
    endpoint_status: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    unsupported_fields: List[str] = field(default_factory=list)
    dimension_scores: List[FundDimensionScore] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    performance_metrics: Optional[FundPerformanceMetrics] = None
    risk_metrics: Optional[FundRiskMetrics] = None
    price_history_status: Optional[str] = None
    performance_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["top_holdings"] = [holding.to_dict() for holding in self.top_holdings]
        payload["dimension_scores"] = [
            dimension.to_dict() for dimension in self.dimension_scores
        ]
        if self.performance_metrics is not None:
            payload["performance_metrics"] = self.performance_metrics.to_dict()
        if self.risk_metrics is not None:
            payload["risk_metrics"] = self.risk_metrics.to_dict()
        if self.participation_assessment is not None:
            payload["participation_assessment"] = (
                self.participation_assessment.to_dict()
            )
        return payload

    def has_performance_or_risk_metrics(self) -> bool:
        performance = self.performance_metrics
        risk = self.risk_metrics
        performance_ok = performance is not None and performance.has_any_return()
        risk_ok = risk is not None and risk.has_any_metric()
        return performance_ok or risk_ok
