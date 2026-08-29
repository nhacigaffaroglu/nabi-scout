"""Pure new-money allocation plan. No writes, providers, or execution.

Answers: given available cash, which existing holdings or approved new
opportunities should receive how much? Layer deficits come from
`build_allocation_intelligence`. Security ranking is eligibility + existing
decision labels only — no new score thresholds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import configured_participation_for_symbol
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.participation_filter_service import (
    PARTICIPATION_UNKNOWN,
    normalize_participation_status,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_allocation_intelligence import (
    AllocationBucket,
    AllocationCompleteness,
    AllocationDimension,
    AllocationIntelligenceView,
    AllocationPolicy,
    DriftStatus,
    build_allocation_intelligence,
    policy_is_configured,
    _classify,
    _map_asset_class,
    _map_market,
)
from services.hybrid_exposure_allocation_policy import (
    HybridExposureAllocationPolicy,
    HybridPortfolioMode,
    NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER,
    NO_ROBUST_UNDERWEIGHT_LAYER,
    resolve_hybrid_allocation_policy,
    select_hybrid_allocation_intent,
)
from services.portfolio_economic_exposure import (
    EconomicExposureBucket,
    InstrumentExposureView,
    PortfolioEconomicExposureView,
    build_economic_exposure,
    classify_instrument_exposure,
)
from services.security_master_service import SecurityMasterService
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.wealth_contract import ASSET_CLASS_EQUITY, ASSET_CLASS_ETF, ASSET_CLASS_FUND
from services.wealth_goal_models import ConversionAssumption
from services.wealth_price_service import normalize_currency

ACTIONABLE_NEW_DECISIONS = frozenset({"GÜÇLÜ ADAY", "ADAY"})
BLOCKED_NEW_DECISIONS = frozenset({
    "İZLE",
    "ARAŞTIR",
    "VERİ EKSİK",
    "UZAK DUR",
    "ELE",
})
DECISION_RANK = {"GÜÇLÜ ADAY": 0, "ADAY": 1}
BLOCKING_PARTICIPATION = "UYGUN DEĞİL"
CONCENTRATION_CAP = Decimal(str(CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT)) / Decimal("100")

REASON_LAYER_DEFICIT = "LAYER_DEFICIT"
REASON_EXISTING_HOLDING_TOPUP = "EXISTING_HOLDING_TOPUP"
REASON_STRONG_CANDIDATE = "STRONG_CANDIDATE"
REASON_CANDIDATE = "CANDIDATE"
REASON_BELOW_MIN_TRADE = "BELOW_MIN_TRADE"
REASON_INSUFFICIENT_CASH = "INSUFFICIENT_CASH_FOR_WHOLE_SHARE"
REASON_DATA_INCOMPLETE = "DATA_INCOMPLETE"
REASON_NOT_ACTIONABLE = "NOT_ACTIONABLE_DECISION"
REASON_OVERWEIGHT_LAYER = "OVERWEIGHT_LAYER"
REASON_FX_REQUIRED = "FX_CONVERSION_REQUIRED"
REASON_PARTICIPATION_BLOCKED = "PARTICIPATION_BLOCKED"
REASON_CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
REASON_MIX_MAINTENANCE = "MIX_MAINTENANCE"
REASON_RESIDUAL_CASH = "RESIDUAL_CASH"
REASON_NO_ELIGIBLE_SECURITY = "NO_ELIGIBLE_SECURITY"
REASON_RESEARCH_NOT_ALLOWED = "RESEARCH_NOT_ALLOWED"
LIVE_BLOCKER_INCOMPLETE = "EXPOSURE_CLASSIFICATION_INCOMPLETE"

CANDIDATE_CLASS_ALIASES = {
    "hisse": "equity",
    "equity": "equity",
    "stock": "equity",
    "etf": "etf",
    "fon": "etf",
    "fund": "etf",
    "sukuk": "sukuk",
    "cash": "cash",
    "nakit": "cash",
}

PRIMARY_DIMENSIONS = (
    AllocationDimension.ASSET_CLASS,
    AllocationDimension.MARKET,
    AllocationDimension.ECONOMIC_EXPOSURE,
)


@dataclass(frozen=True)
class AllocationRecommendation:
    symbol: str
    existing_or_new: str
    layer: str
    decision: Optional[str]
    price: Decimal
    price_currency: str
    quantity: Decimal
    allocated_amount: Decimal
    reason_code: str
    reason_text: str


@dataclass(frozen=True)
class AllocationSkip:
    symbol: str
    reason_code: str
    reason_text: str


@dataclass(frozen=True)
class AllocationPlan:
    input_amount: Decimal
    currency: str
    recommendations: Tuple[AllocationRecommendation, ...]
    total_allocated: Decimal
    residual_cash: Decimal
    skipped: Tuple[AllocationSkip, ...]
    limitations: Tuple[str, ...] = ()
    primary_dimension: Optional[str] = None
    hybrid_allocation_active: bool = False
    hybrid_portfolio_mode: Optional[str] = None
    hybrid_policy: Optional[Dict[str, Any]] = None


@dataclass
class _Security:
    symbol: str
    existing: bool
    layer: str
    decision: Optional[str]
    price: Decimal
    price_currency: str
    asset_class: str
    whole_share: bool


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if not math.isfinite(float(number)):
        return None
    return number


def _valid_price(value: Any) -> Optional[Decimal]:
    price = _dec(value)
    if price is None or price <= 0:
        return None
    return price


def _norm_decision(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _participation_blocked(value: Any) -> bool:
    return not _participation_is_uygun(value)


def _participation_is_uygun(value: Any) -> bool:
    return normalize_participation_status(value) == PARTICIPATION_STATUS_UYGUN


def _research_explicitly_denied(*sources: Any) -> bool:
    """Fail closed only when research_allowed is explicitly false. Missing is not inferred."""
    for source in sources:
        if source is None:
            continue
        value = None
        if isinstance(source, Mapping):
            value = source.get("research_allowed")
        else:
            value = getattr(source, "research_allowed", None)
            if value is None:
                nabi = getattr(source, "nabi", None)
                if nabi is not None:
                    value = getattr(nabi, "research_allowed", None)
        if value is False:
            return True
        if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
            return True
    return False


def _resolve_participation(
    symbol: str,
    *,
    position: Any = None,
    candidate: Optional[Mapping[str, Any]] = None,
    asset: Optional[Mapping[str, Any]] = None,
) -> str:
    nabi = getattr(position, "nabi", None) if position is not None else None
    if nabi is not None:
        status = normalize_participation_status(getattr(nabi, "participation_status", None))
        if status != PARTICIPATION_UNKNOWN:
            return status
    if candidate is not None:
        status = normalize_participation_status(candidate.get("participation_status"))
        if status != PARTICIPATION_UNKNOWN:
            return status
    if asset is not None:
        status = normalize_participation_status(asset.get("participation_status"))
        if status != PARTICIPATION_UNKNOWN:
            return status
    catalog = configured_participation_for_symbol(symbol)
    if catalog is not None:
        return normalize_participation_status(catalog[0])
    return PARTICIPATION_UNKNOWN


def is_actionable_new_decision(decision: Any) -> bool:
    return _norm_decision(decision) in ACTIONABLE_NEW_DECISIONS


def _candidate_asset_class(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    if token in CANDIDATE_CLASS_ALIASES:
        return CANDIDATE_CLASS_ALIASES[token]
    return _map_asset_class(token, is_cash=False)


def _whole_share_required(asset_class: str) -> bool:
    key = str(asset_class or "").strip().lower()
    if key in {ASSET_CLASS_ETF, ASSET_CLASS_FUND, "etf", "fund"}:
        return False
    return key in {ASSET_CLASS_EQUITY, "equity", "hisse"}


def _primary_dimension(policy: AllocationPolicy) -> Optional[AllocationDimension]:
    present = {row.dimension for row in policy.targets}
    for dimension in PRIMARY_DIMENSIONS:
        if dimension in present:
            return dimension
    return None


def _convert(
    amount: Decimal,
    *,
    from_currency: str,
    to_currency: str,
    conversion: Optional[ConversionAssumption],
) -> Optional[Decimal]:
    source = normalize_currency(from_currency)
    target = normalize_currency(to_currency)
    if source == target:
        return amount
    if conversion is None:
        return None
    from_ccy = normalize_currency(conversion.from_currency)
    to_ccy = normalize_currency(conversion.to_currency)
    if from_ccy == source and to_ccy == target:
        return conversion.convert(amount)
    if from_ccy == target and to_ccy == source:
        return amount * conversion.rate
    return None


def _layer_of(
    *,
    dimension: AllocationDimension,
    asset_class: str,
    market: str,
) -> Optional[str]:
    if dimension == AllocationDimension.ASSET_CLASS:
        return asset_class
    if dimension == AllocationDimension.MARKET:
        return market
    return None


def economic_exposure_layers(instrument: InstrumentExposureView) -> Tuple[str, ...]:
    """Sleeves supported by canonical exposure slices. Unknown is never guessed."""
    layers: list[str] = []
    for row in instrument.economic_exposures:
        bucket = str(row.exposure_bucket or "").strip().lower()
        if not bucket or bucket == EconomicExposureBucket.UNKNOWN.value:
            continue
        if float(row.weight_pct or 0) <= 0:
            continue
        if bucket not in layers:
            layers.append(bucket)
    return tuple(layers)


def _allocation_buckets_from_exposure(
    view: PortfolioEconomicExposureView,
) -> Tuple[AllocationBucket, ...]:
    rows: list[AllocationBucket] = []
    for bucket in view.buckets:
        if not bucket.contributing_symbols and not bucket.unpriced_symbols:
            continue
        rows.append(
            AllocationBucket(
                bucket_id=bucket.bucket_id,
                dimension=AllocationDimension.ECONOMIC_EXPOSURE,
                label=bucket.bucket_id,
                observable_market_value=bucket.observable_market_value,
                observable_weight_pct=bucket.observable_weight_pct,
                weight_scope=AllocationCompleteness.OBSERVABLE_ALLOCATION,
                position_count=len(bucket.contributing_symbols) + len(bucket.unpriced_symbols),
                symbols=bucket.contributing_symbols,
                unpriced_symbols=bucket.unpriced_symbols,
                valuation_complete=not bucket.unpriced_symbols,
                limitations=bucket.limitations,
            )
        )
    return tuple(rows)


def _synthetic_instrument_row(
    symbol: str,
    *,
    asset_class: str,
    currency: str,
) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"nm-{symbol}",
        account_id="",
        asset_id="",
        symbol=symbol,
        asset_class=asset_class,
        account_name="",
        quantity=0,
        average_cost=0,
        valuation_currency=currency,
        price=None,
        price_available=False,
        market_value=None,
        cost_basis=0,
        unrealized_pl=None,
        weight_pct=None,
        is_cash=str(asset_class or "").strip().lower() == "cash",
        included_in_base_totals=False,
    )


def _resolve_layers(
    *,
    dimension: AllocationDimension,
    symbol: str,
    asset_class: str,
    market: str,
    position: Any = None,
    instrument: Optional[InstrumentExposureView] = None,
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    canonical_mappings: Optional[Mapping[str, Any]] = None,
    exposure_overrides: Optional[Mapping[str, Any]] = None,
    security_master: Optional[SecurityMasterService] = None,
    identity_service: Optional[Any] = None,
) -> Tuple[str, ...]:
    if dimension != AllocationDimension.ECONOMIC_EXPOSURE:
        layer = _layer_of(dimension=dimension, asset_class=asset_class, market=market)
        return (layer,) if layer else ()
    view = instrument
    if view is None:
        row = position or _synthetic_instrument_row(
            symbol, asset_class=asset_class, currency="USD"
        )
        view = classify_instrument_exposure(
            row,
            user_overrides=exposure_overrides,
            canonical_mappings=canonical_mappings,
            fund_snapshots=fund_snapshots,
            security_master=security_master,
            identity_service=identity_service,
        )
    return economic_exposure_layers(view)


def _existing_positions(view: PortfolioIntelligenceView) -> Tuple[PositionValuationRow, ...]:
    seen: set[str] = set()
    rows: list[PositionValuationRow] = []
    for row in (
        list(view.priced_positions)
        + list(view.unpriced_positions)
        + list(view.foreign_currency_positions)
    ):
        key = row.position_id or f"{row.symbol}:{row.account_id}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return tuple(rows)


def _held_symbols(view: PortfolioIntelligenceView) -> set[str]:
    return {
        str(row.symbol or "").strip().upper()
        for row in _existing_positions(view)
        if str(row.symbol or "").strip()
    }


def allocate_new_money(
    *,
    available_amount: Decimal | float | int | str,
    amount_currency: str,
    portfolio_view: PortfolioIntelligenceView,
    policy: Optional[AllocationPolicy] = None,
    candidates: Sequence[Mapping[str, Any]] = (),
    conversion: Optional[ConversionAssumption] = None,
    assets: Optional[Sequence[dict]] = None,
    positions: Optional[Sequence[dict]] = None,
    minimum_trade_amount: Decimal | float | int | str = 0,
    commission: Decimal | float | int | str = 0,
    allocation: Optional[AllocationIntelligenceView] = None,
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    canonical_mappings: Optional[Mapping[str, Any]] = None,
    exposure_overrides: Optional[Mapping[str, Any]] = None,
    security_master: Optional[SecurityMasterService] = None,
    identity_service: Optional[Any] = None,
    hybrid_policy: Optional[HybridExposureAllocationPolicy] = None,
    enable_hybrid_exposure_allocation: Optional[bool] = None,
) -> AllocationPlan:
    """Return a proposed plan only. Never writes or fetches.

    Hybrid layer selection is resolved once here. Missing flag is OFF.
    """
    amount = Decimal(str(available_amount))
    currency = normalize_currency(amount_currency)
    min_trade = Decimal(str(minimum_trade_amount or 0))
    fee = Decimal(str(commission or 0))
    limitations: list[str] = []
    skipped: list[AllocationSkip] = []

    if amount <= 0:
        return AllocationPlan(
            input_amount=amount,
            currency=currency,
            recommendations=(),
            total_allocated=Decimal("0"),
            residual_cash=max(amount, Decimal("0")),
            skipped=(),
            limitations=("NON_POSITIVE_AMOUNT",),
        )

    exposure_view: Optional[PortfolioEconomicExposureView] = None
    if allocation is not None:
        intelligence = allocation
    else:
        exposure_buckets = None
        preview = _primary_dimension(policy) if policy_is_configured(policy) else None
        if preview == AllocationDimension.ECONOMIC_EXPOSURE:
            exposure_view = build_economic_exposure(
                portfolio_view,
                fund_snapshots=fund_snapshots,
                user_overrides=exposure_overrides,
                canonical_mappings=canonical_mappings,
                assets=assets,
                positions=positions,
                security_master=security_master,
                identity_service=identity_service,
            )
            exposure_buckets = _allocation_buckets_from_exposure(exposure_view)
        intelligence = build_allocation_intelligence(
            portfolio_view,
            policy=policy,
            contribution_amount=amount,
            contribution_currency=currency,
            conversion=conversion,
            assets=assets,
            positions=positions,
            exposure_buckets=exposure_buckets,
            exposure_view=exposure_view,
        )
    hybrid = resolve_hybrid_allocation_policy(
        enable_hybrid_exposure_allocation,
        policy=hybrid_policy,
    )
    limitations.extend(intelligence.limitations)
    if not policy_is_configured(policy):
        return AllocationPlan(
            input_amount=amount,
            currency=currency,
            recommendations=(),
            total_allocated=Decimal("0"),
            residual_cash=amount,
            skipped=(),
            limitations=tuple(dict.fromkeys((*limitations, "TARGET_NOT_CONFIGURED"))),
        )
    assert policy is not None
    dimension = _primary_dimension(policy)
    if dimension is None:
        return AllocationPlan(
            input_amount=amount,
            currency=currency,
            recommendations=(),
            total_allocated=Decimal("0"),
            residual_cash=amount,
            skipped=(),
            limitations=tuple(dict.fromkeys((*limitations, "TARGET_NOT_CONFIGURED"))),
        )

    drift_by_bucket = {
        row.bucket_id: row
        for row in intelligence.drift
        if row.dimension == dimension
    }
    if dimension == AllocationDimension.ECONOMIC_EXPOSURE and exposure_view is not None:
        bucket_value = {
            row.bucket_id: Decimal(str(row.observable_market_value or 0))
            for row in exposure_view.buckets
        }
    elif dimension == AllocationDimension.ECONOMIC_EXPOSURE:
        total_obs = Decimal(str(intelligence.observable_total_market_value or 0))
        bucket_value = {
            row.bucket_id: (total_obs * Decimal(str(row.observable_weight_pct)) / Decimal("100"))
            for row in intelligence.drift
            if row.dimension == dimension and row.observable_weight_pct is not None
        }
    else:
        bucket_value = {
            row.bucket_id: Decimal(str(row.observable_market_value or 0))
            for row in intelligence.asset_class_buckets + intelligence.market_buckets
            if row.dimension == dimension
        }
    target_by_bucket = {
        row.bucket_id: Decimal(str(row.target_weight_pct))
        for row in policy.targets
        if row.dimension == dimension
    }
    unpriced = bool(portfolio_view.unpriced_position_count) or bool(
        intelligence.unpriced_holdings
    )
    intent = select_hybrid_allocation_intent(
        policy=hybrid,
        determinacy=intelligence.exposure_determinacy,
        valuation_complete=not unpriced,
        unpriced=unpriced,
        dimension=dimension.value,
    )
    if hybrid.enabled:
        limitations = [item for item in limitations if item != LIVE_BLOCKER_INCOMPLETE]
    if intent.blocker:
        residual_limits = [intent.blocker]
        if amount > 0:
            residual_limits.append(REASON_RESIDUAL_CASH)
        return AllocationPlan(
            input_amount=amount,
            currency=currency,
            recommendations=(),
            total_allocated=Decimal("0"),
            residual_cash=amount,
            skipped=(),
            limitations=tuple(dict.fromkeys(residual_limits)),
            primary_dimension=dimension.value,
            hybrid_allocation_active=hybrid.enabled,
            hybrid_portfolio_mode=intent.mode.value,
            hybrid_policy=hybrid.to_dict(),
        )
    if intent.use_robust_layers:
        underweight = list(intent.underweight_rows)
        overweight = set(intent.overweight_layers)
    else:
        underweight = sorted(
            (
                row
                for row in drift_by_bucket.values()
                if row.status == DriftStatus.UNDERWEIGHT and row.drift_pct is not None
            ),
            key=lambda row: (row.drift_pct if row.drift_pct is not None else 0.0, row.bucket_id),
        )
        overweight = {
            row.bucket_id
            for row in drift_by_bucket.values()
            if row.status == DriftStatus.OVERWEIGHT
        }

    asset_by_id = {str(row.get("id") or ""): row for row in (assets or [])}
    asset_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in (assets or [])
        if str(row.get("symbol") or "").strip()
    }
    held = _held_symbols(portfolio_view)
    candidates_by_symbol = {
        str(raw.get("symbol") or "").strip().upper(): raw
        for raw in candidates
        if str(raw.get("symbol") or "").strip()
    }
    instruments_by_symbol = {
        str(row.symbol or "").strip().upper(): row
        for row in (exposure_view.instruments if exposure_view is not None else ())
        if str(row.symbol or "").strip()
    }
    existing_mv: Dict[str, Decimal] = {}
    existing_secs: list[_Security] = []
    for row in _existing_positions(portfolio_view):
        symbol = str(row.symbol or "").strip().upper()
        if not symbol or row.is_cash:
            continue
        status = _resolve_participation(
            symbol,
            position=row,
            candidate=candidates_by_symbol.get(symbol),
            asset=asset_by_symbol.get(symbol) or asset_by_id.get(str(row.asset_id or "")),
        )
        if not _participation_is_uygun(status):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_PARTICIPATION_BLOCKED,
                    "Katılım durumu mevcut pozisyon artırımını engelliyor.",
                )
            )
            continue
        if _research_explicitly_denied(
            row,
            candidates_by_symbol.get(symbol),
            asset_by_symbol.get(symbol) or asset_by_id.get(str(row.asset_id or "")),
        ):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_RESEARCH_NOT_ALLOWED,
                    "research_allowed false; araştırma kapalı varlık tahsis edilmez.",
                )
            )
            continue
        asset_class, market = _classify(
            row, asset_by_id=asset_by_id, asset_by_symbol=asset_by_symbol
        )
        layers = _resolve_layers(
            dimension=dimension,
            symbol=symbol,
            asset_class=asset_class,
            market=market,
            position=row,
            instrument=instruments_by_symbol.get(symbol),
            fund_snapshots=fund_snapshots,
            canonical_mappings=canonical_mappings,
            exposure_overrides=exposure_overrides,
            security_master=security_master,
            identity_service=identity_service,
        )
        if not layers:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Katman sınıflandırılamadı.")
            )
            continue
        price = _valid_price(row.price) if row.price_available else None
        if price is None:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Mevcut fiyat yok veya geçersiz.")
            )
            continue
        mv = _convert(
            Decimal(str(row.market_value or 0)),
            from_currency=normalize_currency(row.valuation_currency),
            to_currency=currency,
            conversion=conversion,
        )
        if row.market_value and mv is None:
            skipped.append(
                AllocationSkip(symbol, REASON_FX_REQUIRED, "Pozisyon değeri çevrilemedi.")
            )
            continue
        existing_mv[symbol] = existing_mv.get(symbol, Decimal("0")) + (mv or Decimal("0"))
        mapped = False
        for layer in layers:
            if layer in overweight:
                skipped.append(
                    AllocationSkip(
                        symbol,
                        REASON_OVERWEIGHT_LAYER,
                        f"{layer} katmanı hedefte veya üzerinde; yeni para varsayılan olarak eklenmez.",
                    )
                )
                continue
            existing_secs.append(
                _Security(
                    symbol=symbol,
                    existing=True,
                    layer=layer,
                    decision=None,
                    price=price,
                    price_currency=normalize_currency(row.valuation_currency),
                    asset_class=asset_class,
                    whole_share=_whole_share_required(asset_class),
                )
            )
            mapped = True
        if not mapped:
            continue

    new_secs: list[_Security] = []
    for raw in candidates:
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol or symbol in held:
            continue
        status = _resolve_participation(symbol, candidate=raw)
        if not _participation_is_uygun(status):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_PARTICIPATION_BLOCKED,
                    "Katılım durumu yeni fırsat tahsisini engelliyor.",
                )
            )
            continue
        if _research_explicitly_denied(raw):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_RESEARCH_NOT_ALLOWED,
                    "research_allowed false; araştırma kapalı varlık tahsis edilmez.",
                )
            )
            continue
        if not is_actionable_opportunity(raw):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_NOT_ACTIONABLE,
                    "Yeni fırsat kanonik onaylı fırsat eşiğini karşılamıyor.",
                )
            )
            continue
        price = _valid_price(raw.get("current_price"))
        if price is None:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Geçerli pozitif fiyat yok.")
            )
            continue
        asset_class = _candidate_asset_class(raw.get("asset_type") or raw.get("asset_class"))
        market = _map_market(raw.get("market"))
        layers = _resolve_layers(
            dimension=dimension,
            symbol=symbol,
            asset_class=asset_class,
            market=market,
            instrument=instruments_by_symbol.get(symbol),
            fund_snapshots=fund_snapshots,
            canonical_mappings=canonical_mappings,
            exposure_overrides=exposure_overrides,
            security_master=security_master,
            identity_service=identity_service,
        )
        if not layers:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Yeni fırsat katmanı belirsiz.")
            )
            continue
        mapped = False
        for layer in layers:
            if layer in overweight:
                skipped.append(
                    AllocationSkip(
                        symbol,
                        REASON_OVERWEIGHT_LAYER,
                        f"{layer} katmanı hedefte veya üzerinde.",
                    )
                )
                continue
            new_secs.append(
                _Security(
                    symbol=symbol,
                    existing=False,
                    layer=layer,
                    decision=_norm_decision(raw.get("decision")),
                    price=price,
                    price_currency=normalize_currency(raw.get("currency") or currency),
                    asset_class=asset_class,
                    whole_share=_whole_share_required(asset_class),
                )
            )
            mapped = True
        if not mapped:
            continue

    by_layer: Dict[str, list[_Security]] = {}
    for sec in existing_secs + new_secs:
        by_layer.setdefault(sec.layer, []).append(sec)

    remaining = amount
    total_value = Decimal(str(intelligence.observable_total_market_value or 0))
    recs: Dict[str, AllocationRecommendation] = {}
    fill_mode = "deficit"
    base_ccy = normalize_currency(getattr(portfolio_view, "base_currency", None) or currency)
    initial_total_amount = _convert(
        total_value,
        from_currency=base_ccy,
        to_currency=currency,
        conversion=conversion,
    )
    if initial_total_amount is None:
        initial_total_amount = total_value if base_ccy == currency else Decimal("0")
    post_contribution_book = initial_total_amount + amount

    def _unit_cost(sec: _Security) -> Optional[Decimal]:
        return _convert(
            sec.price,
            from_currency=sec.price_currency,
            to_currency=currency,
            conversion=conversion,
        )

    def _concentration_headroom(symbol: str) -> Decimal:
        cap = CONCENTRATION_CAP * post_contribution_book
        current = existing_mv.get(symbol, Decimal("0"))
        return cap - current

    def _add(sec: _Security, quantity: Decimal, spent: Decimal) -> None:
        nonlocal remaining, total_value
        remaining -= spent
        total_value += spent
        bucket_value[sec.layer] = bucket_value.get(sec.layer, Decimal("0")) + spent
        existing_mv[sec.symbol] = existing_mv.get(sec.symbol, Decimal("0")) + spent
        prior = recs.get(sec.symbol)
        if prior is None:
            if fill_mode == "mix":
                if sec.existing:
                    code, text = (
                        REASON_MIX_MAINTENANCE,
                        "Mevcut pozisyon, hedef karışımı korumak için artırılır.",
                    )
                elif sec.decision == "GÜÇLÜ ADAY":
                    code, text = (
                        REASON_MIX_MAINTENANCE,
                        "GÜÇLÜ ADAY, hedef karışımı korumak için eklenir.",
                    )
                else:
                    code, text = (
                        REASON_MIX_MAINTENANCE,
                        "ADAY, hedef karışımı korumak için eklenir.",
                    )
            elif sec.existing:
                code, text = (
                    REASON_EXISTING_HOLDING_TOPUP,
                    "Mevcut pozisyon, açık katmanda tamamlanır.",
                )
            elif sec.decision == "GÜÇLÜ ADAY":
                code, text = (
                    REASON_STRONG_CANDIDATE,
                    "GÜÇLÜ ADAY, açık katmana yeni fırsat olarak eklenir.",
                )
            else:
                code, text = (
                    REASON_CANDIDATE,
                    "ADAY, açık katmana yeni fırsat olarak eklenir.",
                )
            recs[sec.symbol] = AllocationRecommendation(
                symbol=sec.symbol,
                existing_or_new="existing" if sec.existing else "new",
                layer=sec.layer,
                decision=sec.decision,
                price=sec.price,
                price_currency=sec.price_currency,
                quantity=quantity,
                allocated_amount=spent,
                reason_code=code,
                reason_text=text,
            )
            return
        recs[sec.symbol] = AllocationRecommendation(
            symbol=prior.symbol,
            existing_or_new=prior.existing_or_new,
            layer=prior.layer,
            decision=prior.decision,
            price=prior.price,
            price_currency=prior.price_currency,
            quantity=prior.quantity + quantity,
            allocated_amount=prior.allocated_amount + spent,
            reason_code=prior.reason_code,
            reason_text=prior.reason_text,
        )

    def _needed(layer: str) -> Decimal:
        target_pct = target_by_bucket.get(layer, Decimal("0")) / Decimal("100")
        if target_pct <= 0:
            return Decimal("0")
        if fill_mode == "mix":
            sleeve_spent = Decimal("0")
            for rec in recs.values():
                if rec.layer == layer:
                    sleeve_spent += rec.allocated_amount
            return max(target_pct * amount - sleeve_spent, Decimal("0"))
        current_b = bucket_value.get(layer, Decimal("0"))
        if initial_total_amount <= 0:
            sleeve_spent = Decimal("0")
            for rec in recs.values():
                if rec.layer == layer:
                    sleeve_spent += rec.allocated_amount
            return max(target_pct * amount - sleeve_spent, Decimal("0"))
        if target_pct >= 1:
            return remaining
        fill = (target_pct * total_value - current_b) / (Decimal("1") - target_pct)
        return max(fill, Decimal("0"))

    def _try_buy(sec: _Security, *, qty: Decimal) -> bool:
        unit = _unit_cost(sec)
        if unit is None:
            skipped.append(
                AllocationSkip(sec.symbol, REASON_FX_REQUIRED, "Fiyat para birimi çevrilemedi.")
            )
            return False
        if unit <= 0 or qty <= 0:
            skipped.append(
                AllocationSkip(sec.symbol, REASON_DATA_INCOMPLETE, "Birim maliyet geçersiz.")
            )
            return False
        need = _needed(sec.layer)
        headroom = _concentration_headroom(sec.symbol)
        if headroom <= 0:
            skipped.append(
                AllocationSkip(
                    sec.symbol,
                    REASON_CONCENTRATION_LIMIT,
                    "Tek pozisyon yoğunluk eşiği aşılacağı için eklenmez.",
                )
            )
            return False
        spent = qty * unit + fee
        cap = min(remaining, need, headroom)
        if spent > cap:
            affordable = cap - fee
            if affordable <= 0:
                if sec.whole_share:
                    skipped.append(
                        AllocationSkip(
                            sec.symbol,
                            REASON_INSUFFICIENT_CASH,
                            "Tam pay için nakit yetmiyor.",
                        )
                    )
                return False
            qty = affordable / unit
            if sec.whole_share:
                qty = Decimal(qty.to_integral_value(rounding=ROUND_DOWN))
            if qty <= 0:
                if sec.whole_share:
                    if qty * unit + fee > headroom:
                        skipped.append(
                            AllocationSkip(
                                sec.symbol,
                                REASON_CONCENTRATION_LIMIT,
                                "Tek pozisyon yoğunluk eşiği aşılacağı için eklenmez.",
                            )
                        )
                    else:
                        skipped.append(
                            AllocationSkip(
                                sec.symbol,
                                REASON_INSUFFICIENT_CASH,
                                "Tam pay için nakit yetmiyor.",
                            )
                        )
                return False
            spent = qty * unit + fee
            if spent > cap:
                spent = cap
                qty = (spent - fee) / unit
        if min_trade > 0 and spent < min_trade:
            skipped.append(
                AllocationSkip(
                    sec.symbol,
                    REASON_BELOW_MIN_TRADE,
                    "Tutar minimum etkin işlem eşiğinin altında.",
                )
            )
            return False
        _add(sec, qty, spent)
        return True

    def _max_qty(sec: _Security) -> Decimal:
        unit = _unit_cost(sec)
        if unit is None or unit <= 0:
            return Decimal("0")
        headroom = _concentration_headroom(sec.symbol)
        budget = min(remaining, _needed(sec.layer), max(headroom, Decimal("0"))) - fee
        if budget <= 0:
            return Decimal("0")
        raw = budget / unit
        if sec.whole_share:
            return Decimal(raw.to_integral_value(rounding=ROUND_DOWN))
        return raw

    def _fill_layer(layer: str) -> bool:
        if layer == "cash":
            return False
        securities = by_layer.get(layer, ())
        existing = sorted((row for row in securities if row.existing), key=lambda row: row.symbol)
        newcomers = sorted(
            (row for row in securities if not row.existing),
            key=lambda row: (DECISION_RANK.get(row.decision or "", 99), row.symbol),
        )
        deployed = False
        progressed = True
        while progressed and remaining > 0 and _needed(layer) > 0:
            progressed = False
            for sec in existing:
                qty = Decimal("1") if sec.whole_share else _max_qty(sec)
                if qty > 0 and _try_buy(sec, qty=qty):
                    progressed = True
                    deployed = True
                if remaining <= 0 or _needed(layer) <= 0:
                    break
        for sec in newcomers:
            qty = _max_qty(sec)
            if qty > 0 and _try_buy(sec, qty=qty):
                deployed = True
            elif qty <= 0:
                unit = _unit_cost(sec)
                if unit is None:
                    skipped.append(
                        AllocationSkip(
                            sec.symbol,
                            REASON_FX_REQUIRED,
                            "Fiyat para birimi çevrilemedi.",
                        )
                    )
                elif _concentration_headroom(sec.symbol) <= 0:
                    skipped.append(
                        AllocationSkip(
                            sec.symbol,
                            REASON_CONCENTRATION_LIMIT,
                            "Tek pozisyon yoğunluk eşiği aşılacağı için eklenmez.",
                        )
                    )
                elif sec.whole_share:
                    skipped.append(
                        AllocationSkip(
                            sec.symbol,
                            REASON_INSUFFICIENT_CASH,
                            "Tam pay için nakit yetmiyor.",
                        )
                    )
            if remaining <= 0:
                break
        if not securities:
            skipped.append(
                AllocationSkip(
                    layer,
                    REASON_NO_ELIGIBLE_SECURITY,
                    "Bu katmanda eklemeye uygun katılım onaylı bir varlık yok.",
                )
            )
        return deployed

    for drift in underweight:
        layer = drift.bucket_id
        _fill_layer(layer)
        if layer != "cash" and remaining > 0 and _needed(layer) > 0:
            limitations.append(f"UNFILLED_UNDERWEIGHT:{layer}")

    if remaining > 0 and not underweight and intent.allow_mix_maintenance:
        fill_mode = "mix"
        on_target_layers = sorted(
            row.bucket_id
            for row in drift_by_bucket.values()
            if row.status == DriftStatus.ON_TARGET and row.bucket_id != "cash"
        )
        for layer in on_target_layers:
            if target_by_bucket.get(layer, Decimal("0")) <= 0:
                continue
            _fill_layer(layer)

    total_allocated = sum((row.allocated_amount for row in recs.values()), Decimal("0"))
    if total_allocated > amount:
        total_allocated = amount
    residual = amount - total_allocated
    if residual < 0:
        residual = Decimal("0")
    if residual > 0:
        limitations.append(REASON_RESIDUAL_CASH)
    if intent.mode == HybridPortfolioMode.BOUNDED:
        hybrid_limit = None
        if not underweight:
            hybrid_limit = NO_ROBUST_UNDERWEIGHT_LAYER
        elif total_allocated <= 0:
            first_layer = underweight[0].bucket_id
            hybrid_limit = f"{NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER}:{first_layer}"
        if hybrid_limit:
            limitations = [hybrid_limit, *limitations]
    unique_skips = []
    seen_skip = set()
    for row in skipped:
        key = (row.symbol, row.reason_code)
        if key in seen_skip:
            continue
        seen_skip.add(key)
        unique_skips.append(row)
    return AllocationPlan(
        input_amount=amount,
        currency=currency,
        recommendations=tuple(sorted(recs.values(), key=lambda row: row.symbol)),
        total_allocated=total_allocated,
        residual_cash=residual,
        skipped=tuple(unique_skips),
        limitations=tuple(dict.fromkeys(limitations)),
        primary_dimension=dimension.value,
        hybrid_allocation_active=hybrid.enabled,
        hybrid_portfolio_mode=intent.mode.value,
        hybrid_policy=hybrid.to_dict(),
    )
