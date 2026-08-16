from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from repositories.fund_holdings_repository import FundHoldingsRepository
from services.fund_intelligence_contract import (
    FundHoldingRow,
    FundHoldingsSnapshotView,
    FundIntelligenceView,
    FundParticipationExposure,
)
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)


def _participation_from_row(row: Dict[str, object]) -> str:
    status = str(row.get("participation_status") or PARTICIPATION_UNKNOWN).strip()
    if status in {
        PARTICIPATION_STATUS_UYGUN,
        PARTICIPATION_STATUS_KONTROL_ET,
        PARTICIPATION_STATUS_UYGUN_DEGIL,
        PARTICIPATION_UNKNOWN,
    }:
        return status
    return PARTICIPATION_UNKNOWN


class FundHoldingsService:
    """Read persisted fund holdings — no provider calls on render."""

    def __init__(self, client) -> None:
        self.repo = FundHoldingsRepository(client)
        self.remote_calls = 0

    def get_snapshot(self, fund_symbol: str) -> Optional[FundHoldingsSnapshotView]:
        snap = self.repo.get_latest_snapshot(fund_symbol)
        if snap is None:
            return None
        holdings = self.repo.list_holdings(str(snap["id"]))
        rows = tuple(
            FundHoldingRow(
                underlying_symbol=row.get("underlying_symbol"),
                underlying_name=row.get("underlying_name"),
                weight_pct=float(row["weight_pct"]) if row.get("weight_pct") is not None else None,
                asset_type=row.get("asset_type"),
                participation_status=row.get("participation_status"),
                research_status=row.get("research_status"),
            )
            for row in holdings
        )
        coverage = snap.get("coverage_pct")
        quality = "good" if coverage and float(coverage) >= 80 else "partial"
        limitation = ""
        if coverage is None:
            limitation = "Kapsam bilgisi yok; kısmi look-through."
        elif float(coverage) < 100:
            limitation = f"Yalnızca top-N holding mevcut (~%{float(coverage):.0f} kapsam)."
        return FundHoldingsSnapshotView(
            fund_symbol=str(snap.get("fund_symbol") or fund_symbol).upper(),
            fund_type=str(snap.get("fund_type") or "etf"),
            as_of=str(snap.get("as_of") or ""),
            source=str(snap.get("source") or ""),
            coverage_pct=float(coverage) if coverage is not None else None,
            underlying_count=snap.get("underlying_count"),
            holdings=rows,
            data_quality=quality,
            limitation=limitation,
        )

    def build_intelligence_view(
        self,
        fund_symbol: str,
        *,
        fund_name: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> FundIntelligenceView:
        snapshot = self.get_snapshot(fund_symbol)
        if snapshot is None:
            return FundIntelligenceView(
                fund_symbol=fund_symbol.strip().upper(),
                fund_name=fund_name or fund_symbol.strip().upper(),
                fund_type="etf",
                domicile=None,
                currency=currency,
                holdings_availability="unavailable",
                holdings_as_of=None,
                underlying_count=None,
                top_holdings=(),
                sector_allocation=(),
                country_allocation=(),
                participation_exposure=FundParticipationExposure(
                    uygun_weight_pct=0.0,
                    kontrol_et_weight_pct=0.0,
                    uygun_degil_weight_pct=0.0,
                    unknown_weight_pct=0.0,
                    insufficient_evidence=True,
                    coverage_pct=None,
                    limitation="Holding kanıtı yok; katılım durumu çıkarılamaz.",
                ),
                data_quality="unavailable",
                limitation="Persisted fund holdings bulunamadı.",
            )

        exposure = aggregate_fund_participation(snapshot.holdings, snapshot.coverage_pct)
        top = snapshot.holdings[:10]
        return FundIntelligenceView(
            fund_symbol=snapshot.fund_symbol,
            fund_name=fund_name or snapshot.fund_symbol,
            fund_type=snapshot.fund_type,
            domicile=None,
            currency=currency,
            holdings_availability="partial" if snapshot.data_quality == "partial" else "available",
            holdings_as_of=snapshot.as_of,
            underlying_count=snapshot.underlying_count,
            top_holdings=top,
            sector_allocation=(),
            country_allocation=(),
            participation_exposure=exposure,
            data_quality=snapshot.data_quality,
            limitation=snapshot.limitation,
        )


def aggregate_fund_participation(
    holdings: tuple[FundHoldingRow, ...],
    coverage_pct: Optional[float],
) -> FundParticipationExposure:
    if not holdings:
        return FundParticipationExposure(
            uygun_weight_pct=0.0,
            kontrol_et_weight_pct=0.0,
            uygun_degil_weight_pct=0.0,
            unknown_weight_pct=0.0,
            insufficient_evidence=True,
            coverage_pct=coverage_pct,
            limitation="Holding listesi boş.",
        )

    buckets = {
        PARTICIPATION_STATUS_UYGUN: 0.0,
        PARTICIPATION_STATUS_KONTROL_ET: 0.0,
        PARTICIPATION_STATUS_UYGUN_DEGIL: 0.0,
        PARTICIPATION_UNKNOWN: 0.0,
    }
    known_weight = 0.0
    for row in holdings:
        weight = float(row.weight_pct or 0.0)
        status = str(row.participation_status or PARTICIPATION_UNKNOWN).strip()
        buckets[status] = buckets.get(status, 0.0) + weight
        if status != PARTICIPATION_UNKNOWN:
            known_weight += weight

    unknown = buckets[PARTICIPATION_UNKNOWN]
    if coverage_pct is not None and float(coverage_pct) < 100:
        unknown += max(0.0, 100.0 - float(coverage_pct))

    insufficient = (
        not holdings
        or (coverage_pct is not None and float(coverage_pct) < 50)
        or unknown >= 50
    )
    limitation = ""
    if insufficient:
        limitation = "Yetersiz holding kanıtı; fon katılım durumu belirsiz."
    elif coverage_pct is not None and float(coverage_pct) < 100:
        limitation = "Kısmi holding kapsamı; bilinmeyen ağırlık eklendi."

    return FundParticipationExposure(
        uygun_weight_pct=buckets[PARTICIPATION_STATUS_UYGUN],
        kontrol_et_weight_pct=buckets[PARTICIPATION_STATUS_KONTROL_ET],
        uygun_degil_weight_pct=buckets[PARTICIPATION_STATUS_UYGUN_DEGIL],
        unknown_weight_pct=unknown,
        insufficient_evidence=insufficient,
        coverage_pct=coverage_pct,
        limitation=limitation,
    )
