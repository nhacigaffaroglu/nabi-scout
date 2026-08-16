from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from services.portfolio_construction_contract import ExposureOverlapSignal
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView


def build_exposure_overlap_signals(
    dashboard: PortfolioIntelligenceDashboardView,
) -> Tuple[ExposureOverlapSignal, ...]:
    signals: List[ExposureOverlapSignal] = []
    by_sector: Dict[str, List[tuple[str, float | None]]] = defaultdict(list)
    by_country: Dict[str, List[tuple[str, float | None]]] = defaultdict(list)
    by_institution: Dict[str, List[tuple[str, float | None]]] = defaultdict(list)

    for row in dashboard.enriched_positions:
        if row.valuation.is_cash:
            continue
        sym = row.valuation.symbol
        weight = row.valuation.weight_pct
        sector = row.sector or "Bilinmiyor"
        country = row.country or "Bilinmiyor"
        institution = row.institution or row.account_label or "Bilinmiyor"
        by_sector[sector].append((sym, weight))
        by_country[country].append((sym, weight))
        by_institution[institution].append((sym, weight))

    for sector, items in by_sector.items():
        if len(items) < 2:
            continue
        combined = sum(item[1] or 0.0 for item in items)
        signals.append(
            ExposureOverlapSignal(
                overlap_type="sector_exposure_overlap",
                key=sector,
                label=sector,
                symbol_count=len(items),
                combined_weight_pct=combined if combined else None,
                symbols=tuple(sorted({item[0] for item in items})),
                look_through_status="direct_equity_metadata",
                limitation="İstatistiksel korelasyon iddiası yok; yalnızca sektör örtüşmesi.",
            )
        )

    for country, items in by_country.items():
        if len(items) < 2:
            continue
        combined = sum(item[1] or 0.0 for item in items)
        signals.append(
            ExposureOverlapSignal(
                overlap_type="country_exposure_overlap",
                key=country,
                label=country,
                symbol_count=len(items),
                combined_weight_pct=combined if combined else None,
                symbols=tuple(sorted({item[0] for item in items})),
                look_through_status="direct_equity_metadata",
                limitation="",
            )
        )

    for institution, items in by_institution.items():
        if len(items) < 2:
            continue
        combined = sum(item[1] or 0.0 for item in items)
        signals.append(
            ExposureOverlapSignal(
                overlap_type="institution_concentration",
                key=institution,
                label=institution,
                symbol_count=len(items),
                combined_weight_pct=combined if combined else None,
                symbols=tuple(sorted({item[0] for item in items})),
                look_through_status="account_level",
                limitation="Kurum senaryosu varlık kaybı simülasyonu değildir.",
            )
        )

    fund_rows = [
        row for row in dashboard.enriched_positions
        if row.valuation.asset_class in {"fund", "etf"}
    ]
    if fund_rows:
        signals.append(
            ExposureOverlapSignal(
                overlap_type="fund_lookthrough",
                key="funds",
                label="Fon/ETF",
                symbol_count=len(fund_rows),
                combined_weight_pct=sum(
                    row.valuation.weight_pct or 0.0 for row in fund_rows
                ),
                symbols=tuple(row.valuation.symbol for row in fund_rows),
                look_through_status="LOOK_THROUGH_UNAVAILABLE",
                limitation="Fon içeriği verisi yok; bileşen icat edilmedi.",
            )
        )

    signals.sort(key=lambda item: item.combined_weight_pct or 0.0, reverse=True)
    return tuple(signals)
