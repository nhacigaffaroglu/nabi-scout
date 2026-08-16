from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.participation_filter_service import PARTICIPATION_UNKNOWN
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_account_helpers import format_account_display
from services.portfolio_intelligence_contract import AllocationSlice
from services.portfolio_intelligence_enrichment_contract import (
    ATTENTION_SEVERITY_HIGH,
    ATTENTION_SEVERITY_INFO,
    ATTENTION_SEVERITY_WATCH,
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
    CONCENTRATION_TOP3_THRESHOLD_PCT,
    CoverageMetadata,
    EnrichedPositionRow,
    PortfolioAttentionItem,
    PortfolioIntelligenceDashboardView,
    RESEARCH_COVERAGE_AVAILABLE,
    RESEARCH_COVERAGE_LABELS,
    RESEARCH_COVERAGE_LIMITED,
    RESEARCH_COVERAGE_NOT_EVALUATED,
    RESEARCH_COVERAGE_REVIEW,
    RESEARCH_COVERAGE_UNAVAILABLE,
    UNRESEARCHED_WEIGHT_THRESHOLD_PCT,
    participation_status_from_nabi,
)
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.portfolio_symbol_aggregation import build_consolidated_symbol_rows
from services.research_workflow_service import normalize_research_status

INSTITUTION_CONCENTRATION_THRESHOLD_PCT = 40.0


def infer_research_allowed_from_status(status: Optional[str]) -> Optional[bool]:
    normalized = str(status or "").strip()
    if normalized == PARTICIPATION_STATUS_UYGUN:
        return True
    if normalized == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return False
    if normalized == PARTICIPATION_STATUS_KONTROL_ET:
        return False
    return None


def classify_research_coverage(
    nabi: Optional[InvestmentIntelligenceView],
) -> Tuple[str, str]:
    if nabi is None or not nabi.has_candidate:
        return (
            RESEARCH_COVERAGE_NOT_EVALUATED,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_NOT_EVALUATED],
        )

    status = participation_status_from_nabi(nabi)
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return (
            RESEARCH_COVERAGE_UNAVAILABLE,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_UNAVAILABLE],
        )
    if status == PARTICIPATION_STATUS_KONTROL_ET:
        return (
            RESEARCH_COVERAGE_REVIEW,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_REVIEW],
        )
    if status == PARTICIPATION_UNKNOWN:
        return (
            RESEARCH_COVERAGE_NOT_EVALUATED,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_NOT_EVALUATED],
        )

    workflow_status = normalize_research_status(nabi.research_status)
    if status == PARTICIPATION_STATUS_UYGUN and workflow_status == "TAMAMLANDI":
        return (
            RESEARCH_COVERAGE_AVAILABLE,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_AVAILABLE],
        )
    if nabi.has_participation_snapshot:
        return (
            RESEARCH_COVERAGE_LIMITED,
            RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_LIMITED],
        )
    return (
        RESEARCH_COVERAGE_NOT_EVALUATED,
        RESEARCH_COVERAGE_LABELS[RESEARCH_COVERAGE_NOT_EVALUATED],
    )


def _enrich_position(
    row,
    nabi: Optional[InvestmentIntelligenceView],
    *,
    account: Optional[dict] = None,
    account_weight_pct: Optional[float] = None,
) -> EnrichedPositionRow:
    participation_status = participation_status_from_nabi(nabi)
    coverage_key, coverage_label = classify_research_coverage(nabi)
    account_id = str(row.account_id or "")
    return EnrichedPositionRow(
        valuation=row,
        company_name=(nabi.company_name if nabi else None) or row.symbol,
        account_id=account_id,
        account_label=format_account_display(account) if account else row.account_name,
        institution=(account or {}).get("institution"),
        account_weight_pct=account_weight_pct,
        sector=(nabi.sector_theme if nabi else None),
        industry=(nabi.industry if nabi else None),
        country=(nabi.country if nabi else None),
        participation_status=participation_status,
        research_coverage=coverage_key,
        research_coverage_label=coverage_label,
        research_allowed_inferred=infer_research_allowed_from_status(participation_status),
        research_status=(nabi.research_status if nabi else None),
        has_candidate=bool(nabi and nabi.has_candidate),
        has_participation_snapshot=bool(nabi and nabi.has_participation_snapshot),
    )


def _allocation_by_key(
    rows: List[EnrichedPositionRow],
    *,
    key_fn,
    label_fn,
    total_market_value: float,
    only_priced: bool = True,
) -> Tuple[AllocationSlice, ...]:
    buckets: Dict[str, Tuple[str, float]] = {}
    for row in rows:
        if row.valuation.is_cash:
            continue
        if only_priced and not row.valuation.price_available:
            continue
        if only_priced and row.valuation.market_value is None:
            continue
        key = key_fn(row)
        label = label_fn(row)
        current = buckets.get(key, (label, 0.0))
        buckets[key] = (label, current[1] + float(row.valuation.market_value or 0.0))

    slices: List[AllocationSlice] = []
    for key, (label, market_value) in sorted(
        buckets.items(),
        key=lambda item: item[1][1],
        reverse=True,
    ):
        weight = (
            (market_value / total_market_value) * 100.0
            if total_market_value > 0
            else 0.0
        )
        slices.append(
            AllocationSlice(
                key=key,
                label=label,
                market_value=market_value,
                weight_pct=weight,
            )
        )
    return tuple(slices)


def _participation_bucket(status: str) -> str:
    if status == PARTICIPATION_STATUS_UYGUN:
        return "eligible"
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return "non_eligible"
    if status == PARTICIPATION_STATUS_KONTROL_ET:
        return "review"
    return "unknown"


PARTICIPATION_BUCKET_LABELS = {
    "eligible": "Uygun",
    "non_eligible": "Uygun Değil",
    "review": "Kontrol Et",
    "unknown": "Bilinmiyor",
}


def _weight_for_bucket(
    rows: List[EnrichedPositionRow],
    bucket: str,
    total_mv: float,
) -> float:
    if total_mv <= 0:
        return 0.0
    bucket_mv = sum(
        float(row.valuation.market_value or 0.0)
        for row in rows
        if not row.valuation.is_cash
        and row.valuation.price_available
        and _participation_bucket(row.participation_status) == bucket
    )
    return (bucket_mv / total_mv) * 100.0


def _research_weight(
    rows: List[EnrichedPositionRow],
    *,
    categories: Tuple[str, ...],
    total_mv: float,
) -> float:
    if total_mv <= 0:
        return 0.0
    covered = sum(
        float(row.valuation.market_value or 0.0)
        for row in rows
        if not row.valuation.is_cash
        and row.valuation.price_available
        and row.research_coverage in categories
    )
    return (covered / total_mv) * 100.0


def _build_coverage(
    rows: List[EnrichedPositionRow],
    base: PortfolioIntelligenceView,
) -> CoverageMetadata:
    invested = [row for row in rows if not row.valuation.is_cash]
    if not invested:
        return CoverageMetadata(
            priced_market_value_coverage_pct=0.0,
            participation_status_coverage_pct=0.0,
            sector_coverage_pct=0.0,
            price_data_complete=True,
            limitations=("Portföyde yatırım pozisyonu yok.",),
        )

    priced_count = sum(1 for row in invested if row.valuation.price_available)
    participation_known = sum(
        1
        for row in invested
        if row.participation_status != PARTICIPATION_UNKNOWN
    )
    sector_known = sum(1 for row in invested if row.sector)
    limitations: List[str] = []
    if base.unpriced_position_count:
        limitations.append(
            f"{base.unpriced_position_count} pozisyon için güncel fiyat yok."
        )
    if base.foreign_currency_position_count:
        limitations.append(
            f"{base.foreign_currency_position_count} pozisyon baz para birimi dışında."
        )
    if base.priced_position_count < base.total_position_count:
        limitations.append(
            "Portföy toplamları yalnızca fiyatlı baz-para pozisyonlarını kapsar."
        )

    return CoverageMetadata(
        priced_market_value_coverage_pct=(
            (priced_count / len(invested)) * 100.0 if invested else 0.0
        ),
        participation_status_coverage_pct=(
            (participation_known / len(invested)) * 100.0 if invested else 0.0
        ),
        sector_coverage_pct=(
            (sector_known / len(invested)) * 100.0 if invested else 0.0
        ),
        price_data_complete=base.unpriced_position_count == 0,
        limitations=tuple(limitations),
    )


def _build_attention_items(
    base: PortfolioIntelligenceView,
    rows: List[EnrichedPositionRow],
    *,
    unresearched_weight_pct: float,
    account_allocation: Tuple[AllocationSlice, ...] = (),
) -> Tuple[PortfolioAttentionItem, ...]:
    items: List[PortfolioAttentionItem] = []
    health = base.health

    if health.largest_position_weight_pct >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:
        top = next((row for row in rows if row.valuation.weight_pct), None)
        symbol = top.valuation.symbol if top else "—"
        items.append(
            PortfolioAttentionItem(
                code="HIGH_SINGLE_POSITION_CONCENTRATION",
                severity=ATTENTION_SEVERITY_HIGH,
                title="Yüksek tek pozisyon yoğunlaşması",
                detail=(
                    f"{symbol} portföyün yaklaşık "
                    f"%{health.largest_position_weight_pct:.1f}'ini oluşturuyor."
                ),
            )
        )

    if health.top3_concentration_pct >= CONCENTRATION_TOP3_THRESHOLD_PCT:
        items.append(
            PortfolioAttentionItem(
                code="HIGH_TOP3_CONCENTRATION",
                severity=ATTENTION_SEVERITY_WATCH,
                title="İlk 3 pozisyon yoğunlaşması yüksek",
                detail=(
                    f"En büyük üç pozisyon toplam "
                    f"%{health.top3_concentration_pct:.1f} ağırlıkta."
                ),
            )
        )

    if unresearched_weight_pct >= UNRESEARCHED_WEIGHT_THRESHOLD_PCT:
        items.append(
            PortfolioAttentionItem(
                code="HIGH_UNRESEARCHED_WEIGHT",
                severity=ATTENTION_SEVERITY_WATCH,
                title="Araştırılmamış ağırlık yüksek",
                detail=(
                    f"Portföyün yaklaşık %{unresearched_weight_pct:.1f}'i "
                    "NABI araştırma kapsamı dışında veya sınırlı."
                ),
            )
        )

    if base.unpriced_position_count:
        items.append(
            PortfolioAttentionItem(
                code="MISSING_MARKET_DATA",
                severity=ATTENTION_SEVERITY_WATCH,
                title="Eksik piyasa verisi",
                detail=(
                    f"{base.unpriced_position_count} pozisyon için güncel "
                    "fiyat bulunamadı."
                ),
            )
        )

    for row in rows:
        if row.valuation.is_cash or not row.valuation.price_available:
            continue
        if row.participation_status == PARTICIPATION_STATUS_KONTROL_ET:
            items.append(
                PortfolioAttentionItem(
                    code=f"PARTICIPATION_REVIEW_{row.valuation.symbol}",
                    severity=ATTENTION_SEVERITY_WATCH,
                    title=f"{row.valuation.symbol}: Katılım incelemesi gerekli",
                    detail=(
                        f"Pozisyon ağırlığı "
                        f"%{(row.valuation.weight_pct or 0.0):.1f}."
                    ),
                )
            )
        elif row.participation_status == PARTICIPATION_STATUS_UYGUN_DEGIL:
            items.append(
                PortfolioAttentionItem(
                    code=f"PARTICIPATION_NON_COMPLIANT_{row.valuation.symbol}",
                    severity=ATTENTION_SEVERITY_INFO,
                    title=f"{row.valuation.symbol}: Uygun değil",
                    detail=(
                        "Katılım durumu uygun değil olarak kayıtlı; "
                        "bu bir yatırım tavsiyesi değildir."
                    ),
                )
            )

        if row.research_coverage == RESEARCH_COVERAGE_LIMITED:
            items.append(
                PortfolioAttentionItem(
                    code=f"LIMITED_RESEARCH_{row.valuation.symbol}",
                    severity=ATTENTION_SEVERITY_INFO,
                    title=f"{row.valuation.symbol}: Sınırlı araştırma kanıtı",
                    detail="Araştırma tamamlanmamış veya kanıt sınırlı.",
                )
            )

    for slice_row in account_allocation:
        if slice_row.weight_pct >= INSTITUTION_CONCENTRATION_THRESHOLD_PCT:
            items.append(
                PortfolioAttentionItem(
                    code=f"INSTITUTION_CONCENTRATION_{slice_row.key}",
                    severity=ATTENTION_SEVERITY_WATCH,
                    title=f"Kurum yoğunlaşması: {slice_row.label}",
                    detail=(
                        f"{slice_row.label} portföyün yaklaşık "
                        f"%{slice_row.weight_pct:.1f}'ini oluşturuyor."
                    ),
                )
            )

    return tuple(items)


def _account_market_totals(rows: List[EnrichedPositionRow]) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for row in rows:
        if not row.valuation.price_available or row.valuation.market_value is None:
            continue
        totals[row.account_id] = totals.get(row.account_id, 0.0) + float(
            row.valuation.market_value
        )
    return totals


def build_portfolio_intelligence_dashboard(
    base: PortfolioIntelligenceView,
    *,
    accounts_by_id: Optional[Dict[str, dict]] = None,
    selected_account_id: Optional[str] = None,
    include_cash: bool = True,
) -> PortfolioIntelligenceDashboardView:
    accounts_by_id = accounts_by_id or {}
    source_rows = list(iter_all_position_rows(base))
    if not include_cash:
        source_rows = [row for row in source_rows if not row.is_cash]

    account_totals = {}
    for row in source_rows:
        if row.price_available and row.market_value is not None:
            account_totals[row.account_id] = account_totals.get(row.account_id, 0.0) + float(
                row.market_value
            )

    enriched: List[EnrichedPositionRow] = []
    for row in source_rows:
        account = accounts_by_id.get(str(row.account_id or ""))
        acct_mv = account_totals.get(str(row.account_id or ""), 0.0)
        acct_weight = None
        if (
            row.price_available
            and row.market_value is not None
            and acct_mv > 0
        ):
            acct_weight = (float(row.market_value) / acct_mv) * 100.0
        enriched.append(
            _enrich_position(
                row,
                row.nabi,
                account=account,
                account_weight_pct=acct_weight,
            )
        )

    non_cash_rows = [row for row in enriched if not row.valuation.is_cash]
    total_mv = float(base.priced_total_market_value)
    total_cost = float(base.priced_total_cost_basis)
    return_pct = None
    if total_cost > 0:
        return_pct = (float(base.priced_total_unrealized_pl) / total_cost) * 100.0

    sector_allocation = _allocation_by_key(
        non_cash_rows,
        key_fn=lambda row: row.sector or "unknown",
        label_fn=lambda row: row.sector or "Bilinmiyor",
        total_market_value=total_mv,
    )
    country_allocation = _allocation_by_key(
        non_cash_rows,
        key_fn=lambda row: row.country or "unknown",
        label_fn=lambda row: row.country or "Bilinmiyor",
        total_market_value=total_mv,
    )
    currency_allocation = _allocation_by_key(
        enriched,
        key_fn=lambda row: row.valuation.valuation_currency or "unknown",
        label_fn=lambda row: row.valuation.valuation_currency or "Bilinmiyor",
        total_market_value=total_mv,
    )
    participation_allocation = _allocation_by_key(
        non_cash_rows,
        key_fn=lambda row: _participation_bucket(row.participation_status),
        label_fn=lambda row: PARTICIPATION_BUCKET_LABELS[
            _participation_bucket(row.participation_status)
        ],
        total_market_value=total_mv,
    )
    research_coverage_allocation = _allocation_by_key(
        non_cash_rows,
        key_fn=lambda row: row.research_coverage,
        label_fn=lambda row: row.research_coverage_label,
        total_market_value=total_mv,
    )
    account_allocation = _allocation_by_key(
        enriched,
        key_fn=lambda row: row.account_id or "unknown",
        label_fn=lambda row: row.account_label,
        total_market_value=total_mv,
    )
    consolidated_symbols = build_consolidated_symbol_rows(
        non_cash_rows,
        total_market_value=total_mv,
    )

    research_coverage_weight_pct = _research_weight(
        non_cash_rows,
        categories=(RESEARCH_COVERAGE_AVAILABLE,),
        total_mv=total_mv,
    )
    unresearched_weight_pct = _research_weight(
        non_cash_rows,
        categories=(
            RESEARCH_COVERAGE_NOT_EVALUATED,
            RESEARCH_COVERAGE_LIMITED,
            RESEARCH_COVERAGE_UNAVAILABLE,
        ),
        total_mv=total_mv,
    )

    weights = [
        float(row.valuation.weight_pct or 0.0)
        for row in non_cash_rows
        if row.valuation.weight_pct is not None
    ]
    weights.sort(reverse=True)
    top5 = sum(weights[:5])

    coverage = _build_coverage(non_cash_rows, base)
    attention_items = _build_attention_items(
        base,
        non_cash_rows,
        unresearched_weight_pct=unresearched_weight_pct,
        account_allocation=account_allocation,
    )

    return PortfolioIntelligenceDashboardView(
        base=base,
        enriched_positions=tuple(enriched),
        sector_allocation=sector_allocation,
        country_allocation=country_allocation,
        currency_allocation=currency_allocation,
        participation_allocation=participation_allocation,
        research_coverage_allocation=research_coverage_allocation,
        account_allocation=account_allocation,
        consolidated_symbols=consolidated_symbols,
        selected_account_id=selected_account_id,
        participation_eligible_weight_pct=_weight_for_bucket(non_cash_rows, "eligible", total_mv),
        participation_non_eligible_weight_pct=_weight_for_bucket(
            non_cash_rows, "non_eligible", total_mv
        ),
        participation_review_weight_pct=_weight_for_bucket(non_cash_rows, "review", total_mv),
        participation_unknown_weight_pct=_weight_for_bucket(non_cash_rows, "unknown", total_mv),
        research_coverage_weight_pct=research_coverage_weight_pct,
        unresearched_weight_pct=unresearched_weight_pct,
        top5_concentration_pct=top5,
        return_pct=return_pct,
        coverage=coverage,
        attention_items=attention_items,
    )
