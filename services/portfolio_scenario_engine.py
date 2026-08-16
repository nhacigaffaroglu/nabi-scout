from __future__ import annotations

from typing import Iterable, Mapping, Optional, Tuple

from services.portfolio_construction_contract import ReferenceLimitGap, ScenarioResult
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView


DEFAULT_REFERENCE_LIMITS = {
    "max_single_position_pct": 12.0,
    "max_top3_concentration_pct": 40.0,
    "max_sector_pct": 30.0,
    "max_institution_pct": 50.0,
    "max_kontrol_et_pct": 15.0,
    "min_cash_pct": 5.0,
    "min_research_covered_pct": 60.0,
}


def merge_reference_limits(
    stored: Optional[Mapping[str, object]],
) -> dict[str, Optional[float]]:
    merged = dict(DEFAULT_REFERENCE_LIMITS)
    if stored:
        for key in merged:
            value = stored.get(key)
            if value is not None:
                merged[key] = float(value)
    return merged


def compare_reference_structure(
    *,
    construction_view,
    reference_limits: Mapping[str, Optional[float]],
) -> Tuple[ReferenceLimitGap, ...]:
    conc = construction_view.concentration
    gaps: list[ReferenceLimitGap] = []

    def _gap(dimension: str, current: Optional[float], limit: Optional[float], higher_is_bad: bool) -> None:
        if limit is None or current is None:
            gaps.append(
                ReferenceLimitGap(
                    dimension=dimension,
                    current_value=current,
                    reference_limit=limit,
                    gap_pp=None,
                    status="unknown",
                    note="Yeterli fiyat/kapsam verisi yok.",
                )
            )
            return
        gap_pp = current - limit if higher_is_bad else limit - current
        status = "breach" if (gap_pp > 0 if higher_is_bad else gap_pp < 0) else "within"
        note = (
            f"{dimension} {current:.1f}%; referans limit {limit:.1f}%; "
            f"gap {'+' if gap_pp > 0 else ''}{gap_pp:.1f}pp."
        )
        if status == "breach":
            note += " Yapısal boşluk — işlem talimatı değildir."
        gaps.append(
            ReferenceLimitGap(
                dimension=dimension,
                current_value=current,
                reference_limit=limit,
                gap_pp=round(gap_pp, 2),
                status=status,
                note=note,
            )
        )

    _gap("max_single_position_pct", conc.top1_weight_pct, reference_limits.get("max_single_position_pct"), True)
    _gap("max_top3_concentration_pct", conc.top3_weight_pct, reference_limits.get("max_top3_concentration_pct"), True)
    sector_max = max(
        (row.get("weight_pct") or 0.0 for row in construction_view.sector_allocation),
        default=None,
    )
    _gap("max_sector_pct", sector_max, reference_limits.get("max_sector_pct"), True)
    inst_max = max(
        (row.get("weight_pct") or 0.0 for row in construction_view.institution_allocation),
        default=None,
    )
    _gap("max_institution_pct", inst_max, reference_limits.get("max_institution_pct"), True)
    _gap(
        "max_kontrol_et_pct",
        next(
            (
                row.get("weight_pct")
                for row in construction_view.participation_allocation
                if "kontrol" in str(row.get("label", "")).lower()
            ),
            None,
        ),
        reference_limits.get("max_kontrol_et_pct"),
        True,
    )
    _gap("min_cash_pct", construction_view.cash_weight_pct, reference_limits.get("min_cash_pct"), False)
    researched = 100.0 - (construction_view.unpriced_weight_pct or 0.0)
    _gap("min_research_covered_pct", researched, reference_limits.get("min_research_covered_pct"), False)
    return tuple(gaps)


def build_portfolio_shock_scenario(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    scenario_id: str,
    label: str,
    shock_pct: float,
    symbol_filter: Optional[Iterable[str]] = None,
) -> ScenarioResult:
    allowed = {s.upper() for s in symbol_filter} if symbol_filter else None
    affected: list[dict] = []
    current_total = 0.0
    shocked_total = 0.0
    excluded: list[str] = []

    for row in dashboard.enriched_positions:
        if row.valuation.is_cash:
            continue
        sym = row.valuation.symbol
        if allowed is not None and sym.upper() not in allowed:
            continue
        mv = row.valuation.market_value
        if mv is None:
            excluded.append(sym)
            continue
        current_total += mv
        shocked = mv * (1.0 + shock_pct / 100.0)
        shocked_total += shocked
        affected.append(
            {
                "symbol": sym,
                "current_value": mv,
                "shocked_value": round(shocked, 2),
                "weight_pct": row.valuation.weight_pct,
            }
        )

    portfolio_total = float(dashboard.base.priced_total_market_value or 0.0)
    impact_abs = shocked_total - current_total if affected else None
    impact_pct = (
        (impact_abs / portfolio_total * 100.0)
        if impact_abs is not None and portfolio_total > 0
        else None
    )
    coverage = (
        current_total / portfolio_total * 100.0 if portfolio_total > 0 else None
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_label=label,
        shock_pct=shock_pct,
        affected_positions=tuple(affected),
        current_priced_value=round(current_total, 2) if affected else None,
        shocked_value=round(shocked_total, 2) if affected else None,
        portfolio_impact_abs=round(impact_abs, 2) if impact_abs is not None else None,
        portfolio_impact_pct=round(impact_pct, 2) if impact_pct is not None else None,
        excluded_unpriced_symbols=tuple(sorted(set(excluded))),
        coverage_pct=round(coverage, 2) if coverage is not None else None,
        assumptions=(
            f"Tüm etkilenen fiyatlı pozisyonlara {shock_pct:+.0f}% şok uygulandı.",
            "SCENARIO, NOT FORECAST — olasılık iddiası yok.",
        ),
        limitations=(
            "Fiyatlanmamış pozisyonlar hariç.",
            "VaR veya olasılık tahmini üretilmedi.",
        ),
    )


def build_participation_exclusion_view(
    dashboard: PortfolioIntelligenceDashboardView,
) -> ScenarioResult:
    rows = dashboard.participation_allocation
    affected = [
        {
            "label": row.label,
            "weight_pct": row.weight_pct,
            "market_value": row.market_value,
        }
        for row in rows
    ]
    return ScenarioResult(
        scenario_id="participation_view",
        scenario_label="Katılım durumu dağılımı",
        shock_pct=None,
        affected_positions=tuple(affected),
        current_priced_value=float(dashboard.base.priced_total_market_value or 0.0),
        shocked_value=None,
        portfolio_impact_abs=None,
        portfolio_impact_pct=None,
        excluded_unpriced_symbols=tuple(
            row.symbol for row in dashboard.base.unpriced_positions
        ),
        coverage_pct=dashboard.coverage.priced_market_value_coverage_pct,
        assumptions=("Mevcut katılım durumu ağırlıkları gösterilir.",),
        limitations=("Yatırım tavsiyesi değildir.",),
    )
