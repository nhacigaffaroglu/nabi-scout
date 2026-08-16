from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.fund_holdings_service import FundHoldingsService, aggregate_fund_participation
from services.fund_intelligence_contract import FundHoldingRow
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_contract import AllocationSlice


LOOKTHROUGH_DIRECT = "direct_equity"
LOOKTHROUGH_FUND = "fund_lookthrough"
LOOKTHROUGH_UNAVAILABLE = "lookthrough_unavailable"


@dataclass(frozen=True)
class LookThroughExposureRow:
    underlying_symbol: str
    underlying_name: str
    portfolio_weight_pct: float
    source_symbols: Tuple[str, ...]
    participation_status: str
    look_through_status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioLookThroughView:
    direct_allocation: Tuple[AllocationSlice, ...]
    economic_allocation: Tuple[AllocationSlice, ...]
    participation_allocation: Tuple[AllocationSlice, ...]
    exposure_rows: Tuple[LookThroughExposureRow, ...]
    fund_coverage_pct: Optional[float]
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["exposure_rows"] = [row.to_dict() for row in self.exposure_rows]
        return payload


def _fund_asset_classes() -> frozenset[str]:
    return frozenset({"etf", "fund"})


def build_portfolio_lookthrough(
    *,
    positions: List[dict],
    fund_service: FundHoldingsService,
    total_market_value: float,
) -> PortfolioLookThroughView:
    """Deterministic look-through when persisted fund holdings exist."""
    direct_buckets: Dict[str, float] = defaultdict(float)
    economic_buckets: Dict[str, float] = defaultdict(float)
    participation_buckets: Dict[str, float] = defaultdict(float)
    exposure_rows: List[LookThroughExposureRow] = []
    fund_weights: List[float] = []
    covered_fund_weight = 0.0

    for pos in positions:
        symbol = str(pos.get("symbol") or "").upper()
        asset_class = str(pos.get("asset_class") or "").lower()
        weight = float(pos.get("weight_pct") or 0.0)
        market_value = float(pos.get("market_value") or 0.0)
        if weight <= 0 and market_value <= 0:
            continue

        if asset_class in _fund_asset_classes():
            fund_weights.append(weight)
            snapshot = fund_service.get_snapshot(symbol)
            if snapshot is None or not snapshot.holdings:
                economic_buckets[f"FUND:{symbol}"] += weight
                participation_buckets["insufficient_holdings_evidence"] += weight
                continue
            covered_fund_weight += weight
            for holding in snapshot.holdings:
                underlying = str(holding.underlying_symbol or holding.underlying_name or "UNKNOWN").upper()
                h_weight = (float(holding.weight_pct or 0.0) / 100.0) * weight
                if h_weight <= 0:
                    continue
                economic_buckets[underlying] += h_weight
                p_status = str(holding.participation_status or PARTICIPATION_UNKNOWN)
                participation_buckets[p_status] += h_weight
                exposure_rows.append(
                    LookThroughExposureRow(
                        underlying_symbol=underlying,
                        underlying_name=str(holding.underlying_name or underlying),
                        portfolio_weight_pct=h_weight,
                        source_symbols=(symbol,),
                        participation_status=p_status,
                        look_through_status=LOOKTHROUGH_FUND,
                    )
                )
            if snapshot.coverage_pct is not None and float(snapshot.coverage_pct) < 100:
                unknown = weight * (1.0 - float(snapshot.coverage_pct) / 100.0)
                participation_buckets[PARTICIPATION_UNKNOWN] += unknown
                economic_buckets[f"UNKNOWN:{symbol}"] += unknown
        elif pos.get("is_cash"):
            direct_buckets["cash"] += weight
            economic_buckets["cash"] += weight
        else:
            direct_buckets[symbol] += weight
            economic_buckets[symbol] += weight
            p_status = str(pos.get("participation_status") or PARTICIPATION_UNKNOWN)
            participation_buckets[p_status] += weight
            exposure_rows.append(
                LookThroughExposureRow(
                    underlying_symbol=symbol,
                    underlying_name=str(pos.get("company_name") or symbol),
                    portfolio_weight_pct=weight,
                    source_symbols=(symbol,),
                    participation_status=p_status,
                    look_through_status=LOOKTHROUGH_DIRECT,
                )
            )

    def _slices(buckets: Dict[str, float]) -> Tuple[AllocationSlice, ...]:
        slices: List[AllocationSlice] = []
        for key, wt in sorted(buckets.items(), key=lambda item: item[1], reverse=True):
            mv = (wt / 100.0) * total_market_value if total_market_value > 0 else 0.0
            slices.append(AllocationSlice(key=key, label=key, market_value=mv, weight_pct=wt))
        return tuple(slices)

    fund_coverage = None
    if fund_weights:
        fund_coverage = (covered_fund_weight / sum(fund_weights)) * 100.0

    limitation = ""
    if fund_weights and (fund_coverage or 0) < 100:
        limitation = "Bazı fon/ETF pozisyonlarında holding kanıtı yok; kısmi look-through."

    part_labels = {
        PARTICIPATION_STATUS_UYGUN: "Uygun",
        PARTICIPATION_STATUS_KONTROL_ET: "Kontrol Et",
        PARTICIPATION_STATUS_UYGUN_DEGIL: "Uygun Değil",
        PARTICIPATION_UNKNOWN: "Bilinmiyor",
        "insufficient_holdings_evidence": "Yetersiz holding kanıtı",
    }
    part_slices = tuple(
        AllocationSlice(
            key=key,
            label=part_labels.get(key, key),
            market_value=(wt / 100.0) * total_market_value,
            weight_pct=wt,
        )
        for key, wt in sorted(participation_buckets.items(), key=lambda item: item[1], reverse=True)
    )

    return PortfolioLookThroughView(
        direct_allocation=_slices(direct_buckets),
        economic_allocation=_slices(economic_buckets),
        participation_allocation=part_slices,
        exposure_rows=tuple(exposure_rows),
        fund_coverage_pct=fund_coverage,
        limitation=limitation,
    )
