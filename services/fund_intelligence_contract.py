from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FundHoldingRow:
    underlying_symbol: Optional[str]
    underlying_name: Optional[str]
    weight_pct: Optional[float]
    asset_type: Optional[str]
    participation_status: Optional[str]
    research_status: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundHoldingsSnapshotView:
    fund_symbol: str
    fund_type: str
    as_of: str
    source: str
    coverage_pct: Optional[float]
    underlying_count: Optional[int]
    holdings: Tuple[FundHoldingRow, ...]
    data_quality: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["holdings"] = [row.to_dict() for row in self.holdings]
        return payload


@dataclass(frozen=True)
class FundParticipationExposure:
    uygun_weight_pct: float
    kontrol_et_weight_pct: float
    uygun_degil_weight_pct: float
    unknown_weight_pct: float
    insufficient_evidence: bool
    coverage_pct: Optional[float]
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundIntelligenceView:
    fund_symbol: str
    fund_name: str
    fund_type: str
    domicile: Optional[str]
    currency: Optional[str]
    holdings_availability: str
    holdings_as_of: Optional[str]
    underlying_count: Optional[int]
    top_holdings: Tuple[FundHoldingRow, ...]
    sector_allocation: Tuple[Tuple[str, float], ...]
    country_allocation: Tuple[Tuple[str, float], ...]
    participation_exposure: FundParticipationExposure
    data_quality: str
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["top_holdings"] = [row.to_dict() for row in self.top_holdings]
        payload["participation_exposure"] = self.participation_exposure.to_dict()
        return payload
