"""Portfolio Cockpit presentation. Composes canonical outputs; no new math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.canonical_current_valuation import (
    canonical_current_snapshot,
    canonical_total_wealth_usd,
    canonical_try_equivalent,
)
from services.candidate_pipeline_presentation import display_nabi_score
from services.fx_rate_service import FxRateService
from services.nabi_dashboard_presentation import TryEquivalentView, format_usd_display
from services.portfolio_allocation_intelligence import (
    AllocationIntelligenceView,
    AllocationPolicyStatus,
    DriftStatus,
    build_allocation_intelligence,
)
from services.portfolio_intelligence_contract import AllocationSlice, PortfolioIntelligenceView
from services.ui_table_headers import label_for_column
from services.wealth_goal_models import CurrentWealthSnapshot
from services.wealth_institution_center_presentation import (
    InstitutionCenterView,
    present_institution_center,
)
from services.wealth_performance_center_presentation import (
    PerformanceCenterView,
)

COCKPIT_TITLE = "MEVCUT PORTFÖYÜM"
COST_MISSING_COPY = "Maliyet verisi yok"
BENCHMARK_UNAVAILABLE_COPY = "Karşılaştırılabilir benchmark geçmişi yok; karşılaştırma üretilmedi."
NO_HISTORY_COPY = "Yeterli karşılaştırılabilir geçmiş yok."
LAYER_UNAVAILABLE_COPY = "Kayıtlı katman hedefi yok; hedef yüzdesi uydurulmadı."

ASSET_CLASS_LABELS_TR = {
    "equity": "Hisse",
    "etf": "ETF / Fon",
    "fund": "ETF / Fon",
    "cash": "Nakit",
    "sukuk": "Sukuk",
    "other": "Diğer",
}
MARKET_LABELS_TR = {
    "us": "ABD",
    "tr": "Türkiye",
    "other": "Diğer",
    "unknown": "Bilinmiyor",
}
DRIFT_LABELS = {
    DriftStatus.UNDERWEIGHT: "Eksik ağırlık",
    DriftStatus.ON_TARGET: "Dengeli",
    DriftStatus.OVERWEIGHT: "Aşır ağırlık",
    DriftStatus.INDETERMINATE: "Belirsiz",
}

HOLDINGS_TABLE_COLUMNS = (
    "symbol",
    "asset_type",
    "institution",
    "quantity",
    "current_price",
    "currency",
    "market_value",
    "weight_pct",
    "cost_basis",
    "unrealized_pl",
    "pl_pct",
    "nabi_score",
    "decision",
)


@dataclass(frozen=True)
class FxEvidence:
    pair: str
    rate: Optional[float]
    source: Optional[str]
    as_of: Optional[str]
    freshness: str


@dataclass(frozen=True)
class CockpitHero:
    usd_label: str
    try_label: Optional[str]
    try_limitation: Optional[str]
    gain_usd_label: Optional[str]
    gain_try_label: Optional[str]
    gain_pct_label: Optional[str]
    period_label: Optional[str]
    holdings_count: int
    largest_symbol: Optional[str]
    largest_weight_label: Optional[str]
    valuation_complete: bool
    valuation_label: str


@dataclass(frozen=True)
class CockpitAllocationSlice:
    key: str
    label: str
    market_value: float
    weight_pct: float


@dataclass(frozen=True)
class LayerRow:
    label: str
    actual_pct: float
    target_pct: Optional[float]
    status: str


@dataclass(frozen=True)
class HoldingWeightRow:
    symbol: str
    market_value: float
    weight_pct: float
    gain_label: Optional[str]
    gain_pct: Optional[float] = None


@dataclass(frozen=True)
class GainLossRow:
    symbol: str
    gain_usd: Optional[float]
    gain_pct: Optional[float]
    market_value: float
    weight_pct: float
    cost_missing: bool


@dataclass(frozen=True)
class HoldingsTableRow:
    symbol: str
    asset_type: str
    institution: str
    quantity: Optional[float]
    current_price: Optional[float]
    currency: str
    market_value: Optional[float]
    weight_pct: Optional[float]
    cost_basis: Optional[float]
    unrealized_pl: Optional[float]
    pl_pct: Optional[float]
    nabi_score: Optional[float]
    decision: str
    cost_missing: bool


@dataclass(frozen=True)
class PortfolioCockpitView:
    title: str
    hero: CockpitHero
    fx_evidence: FxEvidence
    snapshot: CurrentWealthSnapshot
    usd_total: float
    try_equivalent: TryEquivalentView
    asset_allocation: Tuple[CockpitAllocationSlice, ...]
    market_allocation: Tuple[CockpitAllocationSlice, ...]
    layer_rows: Tuple[LayerRow, ...]
    layer_available: bool
    layer_limitation: Optional[str]
    holding_weights: Tuple[HoldingWeightRow, ...]
    winners: Tuple[GainLossRow, ...]
    losers: Tuple[GainLossRow, ...]
    gain_available: bool
    institutions: InstitutionCenterView
    holdings_table: Tuple[HoldingsTableRow, ...]
    table_headers: Tuple[str, ...]
    performance: Optional[PerformanceCenterView]
    benchmark_available: bool
    benchmark_limitation: Optional[str]


def present_fx_evidence(fx_service: Optional[FxRateService]) -> FxEvidence:
    if fx_service is None:
        return FxEvidence("USD/TRY", None, None, None, "Yok")
    row = fx_service.get_rate_row(base_currency="USD", quote_currency="TRY")
    if row is None:
        return FxEvidence("USD/TRY", None, None, None, "Yok")
    freshness = "Eski" if row.stale else "Güncel"
    return FxEvidence(
        pair="USD/TRY",
        rate=row.rate,
        source=row.source or None,
        as_of=row.rate_date or None,
        freshness=freshness,
    )


def _cost_missing(row) -> bool:
    cost = row.cost_basis
    if cost is None:
        return True
    try:
        return float(cost) <= 0
    except (TypeError, ValueError):
        return True


def _pl_pct(row) -> Optional[float]:
    if _cost_missing(row) or row.unrealized_pl is None:
        return None
    try:
        return float(row.unrealized_pl) / float(row.cost_basis) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _asset_label(asset_class: str) -> str:
    return ASSET_CLASS_LABELS_TR.get(str(asset_class or "").lower(), ASSET_CLASS_LABELS_TR["other"])


def _market_label(key: str) -> str:
    return MARKET_LABELS_TR.get(str(key or "").lower(), MARKET_LABELS_TR["unknown"])


def _allocation_from_buckets(
    buckets,
    labels: Mapping[str, str],
) -> Tuple[CockpitAllocationSlice, ...]:
    slices = []
    for bucket in buckets:
        if bucket.observable_market_value in (None, 0, 0.0):
            continue
        slices.append(
            CockpitAllocationSlice(
                key=bucket.bucket_id,
                label=labels.get(bucket.bucket_id, bucket.label),
                market_value=float(bucket.observable_market_value),
                weight_pct=float(bucket.observable_weight_pct or 0.0),
            )
        )
    return tuple(slices)


def _layer_rows(intel: AllocationIntelligenceView) -> Tuple[Tuple[LayerRow, ...], bool, Optional[str]]:
    if intel.target_policy_status != AllocationPolicyStatus.CONFIGURED:
        return (), False, LAYER_UNAVAILABLE_COPY
    rows: list[LayerRow] = []
    for drift in intel.drift:
        rows.append(
            LayerRow(
                label=drift.bucket_id,
                actual_pct=float(drift.observable_weight_pct or 0.0),
                target_pct=(
                    float(drift.target_weight_pct)
                    if drift.target_weight_pct is not None
                    else None
                ),
                status=DRIFT_LABELS.get(drift.status, drift.status.value),
            )
        )
    return tuple(rows), True, None


def _hero(
    *,
    view: PortfolioIntelligenceView,
    snapshot: CurrentWealthSnapshot,
    try_view: TryEquivalentView,
    performance: Optional[PerformanceCenterView],
) -> CockpitHero:
    usd = canonical_total_wealth_usd(view)
    gain_usd = None
    gain_pct = None
    cost_safe = bool(view.priced_positions) and all(
        not _cost_missing(row) for row in view.priced_positions
    )
    cost = float(view.priced_total_cost_basis or 0.0)
    if cost_safe and cost > 0 and view.priced_total_unrealized_pl is not None:
        gain_usd = float(view.priced_total_unrealized_pl)
        gain_pct = gain_usd / cost * 100.0
    largest = max(
        view.priced_positions,
        key=lambda row: float(row.market_value or 0.0),
        default=None,
    )
    period = None
    if (
        performance is not None
        and performance.sufficient
        and performance.history is not None
        and performance.history.return_pct is not None
    ):
        period = f"{performance.period.value}: {float(performance.history.return_pct):.2f}%"
    return CockpitHero(
        usd_label=format_usd_display(usd),
        try_label=f"≈ {try_view.label}" if try_view.available and try_view.label else None,
        try_limitation=None if try_view.available else try_view.limitation,
        gain_usd_label=format_usd_display(gain_usd) if gain_usd is not None else None,
        gain_try_label=None,
        gain_pct_label=f"{gain_pct:+.1f}%" if gain_pct is not None else None,
        period_label=period,
        holdings_count=len(view.priced_positions),
        largest_symbol=largest.symbol if largest else None,
        largest_weight_label=(
            f"%{largest.weight_pct:.1f}" if largest and largest.weight_pct is not None else None
        ),
        valuation_complete=snapshot.valuation_complete,
        valuation_label="Değerleme tamam" if snapshot.valuation_complete else "Değerleme kısmi",
    )


def _holdings_table(
    view: PortfolioIntelligenceView,
    *,
    accounts: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> Tuple[HoldingsTableRow, ...]:
    account_by_id = {str(row.get("id") or ""): row for row in accounts}
    candidate_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row for row in candidates
    }
    rows: list[HoldingsTableRow] = []
    for row in view.priced_positions:
        account = account_by_id.get(str(row.account_id) or "")
        institution = str((account or {}).get("institution") or row.account_name or "—")
        candidate = candidate_by_symbol.get(str(row.symbol or "").strip().upper(), {})
        missing = _cost_missing(row)
        rows.append(
            HoldingsTableRow(
                symbol=row.symbol,
                asset_type=_asset_label(row.asset_class),
                institution=institution,
                quantity=row.quantity,
                current_price=row.price,
                currency=row.valuation_currency,
                market_value=row.market_value,
                weight_pct=row.weight_pct,
                cost_basis=None if missing else row.cost_basis,
                unrealized_pl=None if missing else row.unrealized_pl,
                pl_pct=_pl_pct(row),
                nabi_score=display_nabi_score(candidate) if candidate else None,
                decision=str(candidate.get("decision") or "—") if candidate else "—",
                cost_missing=missing,
            )
        )
    return tuple(rows)


def build_portfolio_cockpit(
    view: PortfolioIntelligenceView,
    *,
    fx_service: Optional[FxRateService] = None,
    accounts: Sequence[Mapping[str, Any]] = (),
    assets: Sequence[Mapping[str, Any]] = (),
    positions: Sequence[Mapping[str, Any]] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    allocation: Optional[AllocationIntelligenceView] = None,
    performance: Optional[PerformanceCenterView] = None,
    benchmark_available: bool = False,
) -> PortfolioCockpitView:
    snapshot = canonical_current_snapshot(view, positions=positions, assets=assets)
    try_view = canonical_try_equivalent(view, fx_service)
    intel = allocation or build_allocation_intelligence(
        view,
        assets=list(assets),
        positions=list(positions),
    )
    layers, layer_ok, layer_limit = _layer_rows(intel)
    weights = []
    gain_rows = []
    for row in view.priced_positions:
        if row.market_value is None:
            continue
        missing = _cost_missing(row)
        gain_label = None
        gain_pct = None
        if not missing and row.unrealized_pl is not None:
            gain_label = format_usd_display(float(row.unrealized_pl))
            gain_pct = _pl_pct(row)
        weights.append(
            HoldingWeightRow(
                symbol=row.symbol,
                market_value=float(row.market_value),
                weight_pct=float(row.weight_pct or 0.0),
                gain_label=gain_label,
                gain_pct=gain_pct,
            )
        )
        gain_rows.append(
            GainLossRow(
                symbol=row.symbol,
                gain_usd=None if missing else (float(row.unrealized_pl) if row.unrealized_pl is not None else None),
                gain_pct=_pl_pct(row),
                market_value=float(row.market_value),
                weight_pct=float(row.weight_pct or 0.0),
                cost_missing=missing,
            )
        )
    ranked = [row for row in gain_rows if not row.cost_missing and row.gain_usd is not None]
    winners = tuple(sorted(ranked, key=lambda item: item.gain_usd or 0.0, reverse=True)[:5])
    losers = tuple(sorted(ranked, key=lambda item: item.gain_usd or 0.0)[:5])
    return PortfolioCockpitView(
        title=COCKPIT_TITLE,
        hero=_hero(view=view, snapshot=snapshot, try_view=try_view, performance=performance),
        fx_evidence=present_fx_evidence(fx_service),
        snapshot=snapshot,
        usd_total=canonical_total_wealth_usd(view),
        try_equivalent=try_view,
        asset_allocation=_allocation_from_buckets(intel.asset_class_buckets, ASSET_CLASS_LABELS_TR),
        market_allocation=_allocation_from_buckets(intel.market_buckets, MARKET_LABELS_TR),
        layer_rows=layers,
        layer_available=layer_ok,
        layer_limitation=layer_limit,
        holding_weights=tuple(weights),
        winners=winners,
        losers=losers,
        gain_available=bool(ranked),
        institutions=present_institution_center(view, list(accounts)),
        holdings_table=_holdings_table(view, accounts=accounts, candidates=candidates),
        table_headers=tuple(label_for_column(column) for column in HOLDINGS_TABLE_COLUMNS),
        performance=performance,
        benchmark_available=benchmark_available,
        benchmark_limitation=None if benchmark_available else BENCHMARK_UNAVAILABLE_COPY,
    )


def allocation_sums_to_total(slices: Sequence[CockpitAllocationSlice], total: float) -> bool:
    if not slices:
        return total == 0
    return abs(sum(row.market_value for row in slices) - total) < 0.02


def weights_sum_near_100(rows: Sequence[HoldingWeightRow]) -> bool:
    if not rows:
        return True
    return abs(sum(row.weight_pct for row in rows) - 100.0) < 0.05
