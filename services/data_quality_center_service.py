from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    severity: str
    label: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataQualitySummary:
    issue_count: int
    partial_valuation: bool
    issues: Tuple[DataQualityIssue, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_count": self.issue_count,
            "partial_valuation": self.partial_valuation,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def build_data_quality_summary(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    fx_stale: bool = False,
    fund_holdings_stale: bool = False,
) -> DataQualitySummary:
    base = dashboard.base
    issues: List[DataQualityIssue] = []

    if base.unpriced_position_count:
        issues.append(
            DataQualityIssue(
                code="missing_prices",
                severity="watch",
                label="Eksik fiyat",
                detail=f"{base.unpriced_position_count} pozisyon fiyatlanmadı.",
            )
        )
    if base.foreign_currency_position_count and not base.fx_supported:
        issues.append(
            DataQualityIssue(
                code="missing_fx",
                severity="watch",
                label="Eksik FX",
                detail="Bazı döviz pozisyonları dönüştürülemedi.",
            )
        )
    if fx_stale:
        issues.append(
            DataQualityIssue(
                code="stale_fx",
                severity="info",
                label="Eski kur",
                detail="Persisted FX kurları güncel olmayabilir.",
            )
        )
    if fund_holdings_stale:
        issues.append(
            DataQualityIssue(
                code="stale_fund_holdings",
                severity="info",
                label="Eski fon holding",
                detail="Fon/ETF holding snapshot güncellenmeli.",
            )
        )
    if dashboard.participation_unknown_weight_pct >= 20:
        issues.append(
            DataQualityIssue(
                code="participation_unknown",
                severity="info",
                label="Katılım bilinmiyor",
                detail=f"%{dashboard.participation_unknown_weight_pct:.0f} bilinmeyen katılım ağırlığı.",
            )
        )
    if dashboard.unresearched_weight_pct >= 20:
        issues.append(
            DataQualityIssue(
                code="research_gap",
                severity="info",
                label="Araştırma boşluğu",
                detail=f"%{dashboard.unresearched_weight_pct:.0f} değerlendirilmemiş ağırlık.",
            )
        )

    partial = base.unpriced_position_count > 0 or (
        base.foreign_currency_position_count > 0 and not base.fx_supported
    )
    return DataQualitySummary(
        issue_count=len(issues),
        partial_valuation=partial,
        issues=tuple(issues),
    )
