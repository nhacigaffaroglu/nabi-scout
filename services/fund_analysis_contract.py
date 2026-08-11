from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

ANALYSIS_KIND_FUND = "fund"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

PARTICIPATION_SOURCE_CONFIGURED = "configured"

DIMENSION_COST = "Maliyet"
DIMENSION_LIQUIDITY = "Likidite"
DIMENSION_CONCENTRATION = "Yoğunlaşma"
DIMENSION_DATA_QUALITY = "Veri kalitesi"

LABEL_INCELEME_UYGUN = "İncelemeye uygun"
LABEL_VERI_YETERSIZ = "Veri yetersiz"
LABEL_YUKSEK_MALIYET = "Yüksek maliyet"
LABEL_YOGUNLASMA_RISKI = "Yoğunlaşma riski"
LABEL_CONFIGURED_PARTICIPATION = "Yapılandırılmış katılım ETF'si"


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
    data_completeness_pct: float = 0.0
    analysis_confidence: str = CONFIDENCE_LOW
    endpoint_status: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    unsupported_fields: List[str] = field(default_factory=list)
    dimension_scores: List[FundDimensionScore] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["top_holdings"] = [holding.to_dict() for holding in self.top_holdings]
        payload["dimension_scores"] = [
            dimension.to_dict() for dimension in self.dimension_scores
        ]
        return payload
