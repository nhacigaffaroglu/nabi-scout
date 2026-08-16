from __future__ import annotations

from typing import List, Optional, Sequence

from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.portfolio_performance_intelligence_service import PortfolioIntelligenceV13View
from services.wave3_intelligence_service import Wave3IntelligenceView


def build_portfolio_insights(
    *,
    dashboard: PortfolioIntelligenceDashboardView,
    v13: Optional[PortfolioIntelligenceV13View] = None,
    wave3: Optional[Wave3IntelligenceView] = None,
) -> List[str]:
    insights: List[str] = []
    base = dashboard.base
    conc = wave3.construction.concentration if wave3 else None

    if conc and conc.top3_weight_pct is not None:
        insights.append(
            f"En büyük üç pozisyon portföyün %{conc.top3_weight_pct:.0f}'ini oluşturuyor."
        )
    elif dashboard.consolidated_symbols:
        top3 = sum(
            float(item.portfolio_weight_pct or 0.0)
            for item in sorted(
                dashboard.consolidated_symbols,
                key=lambda row: float(row.portfolio_weight_pct or 0.0),
                reverse=True,
            )[:3]
        )
        if top3 > 0:
            insights.append(f"En büyük üç pozisyon portföyün %{top3:.0f}'ini oluşturuyor.")

    if base.unpriced_position_count:
        priced_pct = base.health.priced_position_coverage_pct
        insights.append(
            f"Değerlemenin %{100 - priced_pct:.0f}'i güncel fiyat eksikliği nedeniyle "
            f"hesaplanamıyor ({base.unpriced_position_count} pozisyon)."
        )

    if v13 and v13.performance.investment_gain is not None and v13.performance.net_external_flow:
        gain = v13.performance.investment_gain
        flow = v13.performance.net_external_flow
        if abs(flow) > abs(gain) * 0.5 and flow > 0:
            insights.append(
                "Portföy değerindeki değişimin önemli bölümü yeni katkıdan geliyor olabilir."
            )
        elif gain > 0 and abs(gain) > abs(flow):
            insights.append(
                "Portföy değerindeki artışın büyük bölümü yatırım performansından geliyor."
            )

    if dashboard.participation_unknown_weight_pct >= 15:
        insights.append(
            f"Katılım durumu bilinmeyen pozisyonlar %{dashboard.participation_unknown_weight_pct:.0f} ağırlıkta."
        )

    if wave3 and wave3.reference_gaps:
        breaches = [gap for gap in wave3.reference_gaps if gap.status == "breach"]
        if breaches:
            labels = ", ".join(gap.dimension for gap in breaches[:3])
            insights.append(f"Referans limit üzerinde yapısal boşluk: {labels}.")

    return insights[:5]
