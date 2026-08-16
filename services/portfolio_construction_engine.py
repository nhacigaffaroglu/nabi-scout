from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from services.portfolio_construction_contract import (
    ConcentrationMetrics,
    ExposureOverlapSignal,
    PortfolioConstructionView,
    RiskBudgetDimension,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
    CONCENTRATION_TOP3_THRESHOLD_PCT,
    PortfolioIntelligenceDashboardView,
)


def _status_for_threshold(value: Optional[float], threshold: Optional[float]) -> str:
    if value is None or threshold is None:
        return "unknown"
    if value > threshold:
        return "above_threshold"
    return "within_threshold"


def _build_concentration(dashboard: PortfolioIntelligenceDashboardView) -> ConcentrationMetrics:
    consolidated = dashboard.consolidated_symbols
    limitations: List[str] = []
    if not consolidated:
        return ConcentrationMetrics(
            top1_symbol=None,
            top1_weight_pct=None,
            top3_weight_pct=None,
            top5_weight_pct=None,
            hhi_proxy=None,
            limitations=("Fiyatlı pozisyon yok.",),
        )

    weights = [
        (row.symbol, row.portfolio_weight_pct)
        for row in consolidated
        if row.portfolio_weight_pct is not None
    ]
    if not weights:
        limitations.append("Ağırlık hesaplanamadı; fiyat eksikliği.")
        return ConcentrationMetrics(
            top1_symbol=consolidated[0].symbol if consolidated else None,
            top1_weight_pct=None,
            top3_weight_pct=None,
            top5_weight_pct=dashboard.top5_concentration_pct,
            hhi_proxy=None,
            limitations=tuple(limitations),
        )

    weights.sort(key=lambda item: item[1] or 0.0, reverse=True)
    top1 = weights[0]
    top3 = sum(item[1] or 0.0 for item in weights[:3])
    top5 = sum(item[1] or 0.0 for item in weights[:5])
    hhi = sum(((item[1] or 0.0) / 100.0) ** 2 for item in weights) * 10000.0
    return ConcentrationMetrics(
        top1_symbol=top1[0],
        top1_weight_pct=top1[1],
        top3_weight_pct=top3,
        top5_weight_pct=top5,
        hhi_proxy=round(hhi, 2),
        limitations=tuple(limitations),
    )


def _slice_dicts(slices) -> Tuple[Dict[str, object], ...]:
    return tuple(
        {
            "key": row.key,
            "label": row.label,
            "market_value": row.market_value,
            "weight_pct": row.weight_pct,
        }
        for row in slices
    )


def build_portfolio_construction_view(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    default_thresholds: Optional[Mapping[str, float]] = None,
) -> PortfolioConstructionView:
    thresholds = dict(default_thresholds or {})
    single_threshold = thresholds.get(
        "max_single_position_pct",
        CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
    )
    top3_threshold = thresholds.get(
        "max_top3_concentration_pct",
        CONCENTRATION_TOP3_THRESHOLD_PCT,
    )
    concentration = _build_concentration(dashboard)
    base = dashboard.base
    priced_total = float(base.priced_total_market_value or 0.0)
    unpriced_count = len(base.unpriced_positions)
    total_positions = base.total_position_count
    priced_weight_pct = (
        (priced_total / float(base.priced_total_market_value) * 100.0)
        if base.priced_total_market_value
        else None
    )
    cash_weight = next(
        (row.weight_pct for row in dashboard.currency_allocation if row.key == "cash"),
        None,
    )
    limitations: List[str] = list(dashboard.coverage.limitations)
    if unpriced_count:
        limitations.append(f"{unpriced_count} fiyatlanmamış pozisyon yapı analizine dahil değil.")

    risk_budget: List[RiskBudgetDimension] = [
        RiskBudgetDimension(
            dimension="single_position",
            current_value=concentration.top1_weight_pct,
            threshold=single_threshold,
            status=_status_for_threshold(concentration.top1_weight_pct, single_threshold),
            evidence=f"En büyük pozisyon: {concentration.top1_symbol or '—'}",
            limitation="Yapısal yoğunlaşma; volatilite/VaR değildir.",
        ),
        RiskBudgetDimension(
            dimension="top3_concentration",
            current_value=concentration.top3_weight_pct,
            threshold=top3_threshold,
            status=_status_for_threshold(concentration.top3_weight_pct, top3_threshold),
            evidence="İlk 3 pozisyon ağırlığı",
            limitation="",
        ),
        RiskBudgetDimension(
            dimension="participation_review_exposure",
            current_value=dashboard.participation_review_weight_pct,
            threshold=thresholds.get("max_kontrol_et_pct"),
            status=_status_for_threshold(
                dashboard.participation_review_weight_pct,
                thresholds.get("max_kontrol_et_pct"),
            ),
            evidence="Kontrol Et ağırlığı",
            limitation="Katılım durumu karar destek verisidir.",
        ),
        RiskBudgetDimension(
            dimension="unresearched_exposure",
            current_value=dashboard.unresearched_weight_pct,
            threshold=thresholds.get("min_research_covered_pct"),
            status="watch" if dashboard.unresearched_weight_pct > 20 else "within_threshold",
            evidence="Araştırma kapsamı dışı ağırlık",
            limitation="",
        ),
        RiskBudgetDimension(
            dimension="unpriced_exposure",
            current_value=(
                100.0 - priced_weight_pct if priced_weight_pct is not None else None
            ),
            threshold=None,
            status="watch" if unpriced_count else "within_threshold",
            evidence=f"{unpriced_count}/{total_positions} fiyatlanmamış",
            limitation="Fiyat eksikliği ağırlık hesabını sınırlar.",
        ),
        RiskBudgetDimension(
            dimension="cash_level",
            current_value=cash_weight,
            threshold=thresholds.get("min_cash_pct"),
            status=_status_for_threshold(cash_weight, thresholds.get("min_cash_pct")),
            evidence="Nakit ağırlığı",
            limitation="",
        ),
    ]

    from services.portfolio_exposure_overlap_engine import build_exposure_overlap_signals

    return PortfolioConstructionView(
        concentration=concentration,
        sector_allocation=_slice_dicts(dashboard.sector_allocation),
        country_allocation=_slice_dicts(dashboard.country_allocation),
        institution_allocation=_slice_dicts(dashboard.account_allocation),
        participation_allocation=_slice_dicts(dashboard.participation_allocation),
        research_coverage_allocation=_slice_dicts(dashboard.research_coverage_allocation),
        currency_allocation=_slice_dicts(dashboard.currency_allocation),
        cash_weight_pct=cash_weight,
        priced_weight_pct=priced_weight_pct,
        unpriced_weight_pct=(
            100.0 - priced_weight_pct if priced_weight_pct is not None else None
        ),
        overlap_signals=build_exposure_overlap_signals(dashboard),
        risk_budget=tuple(risk_budget),
        limitations=tuple(dict.fromkeys(limitations)),
    )
