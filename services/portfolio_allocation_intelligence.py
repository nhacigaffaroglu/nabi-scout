from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple

from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_asset_classification import (
    CASH_SYMBOL,
    KNOWN_EQUITY_TR,
    KNOWN_EQUITY_US,
    KNOWN_ETF_SYMBOLS,
    TF_PARTICIPATION_SYMBOL,
    resolve_asset_metadata,
)
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_SUKUK,
    WealthValidationError,
)
from services.wealth_goal_models import (
    ConversionAssumption,
    current_wealth_from_portfolio_view,
)
from services.wealth_price_service import normalize_currency

# Drift-review tolerance in percentage points. Not financial advice.
ALLOCATION_DRIFT_TOLERANCE_PCT = 2.0
TARGET_SUM_EPSILON_PCT = 0.05
WEIGHT_QUANT = 4

KNOWN_MARKET_SYMBOLS = (
    KNOWN_ETF_SYMBOLS | KNOWN_EQUITY_US | KNOWN_EQUITY_TR | {CASH_SYMBOL, TF_PARTICIPATION_SYMBOL}
)
US_MARKET_ALIASES = frozenset({"US", "USA", "ABD"})
TR_MARKET_ALIASES = frozenset({"TR", "BIST", "TURKEY", "TURKIYE", "TÜRKİYE"})
ASSET_CLASS_KEYS = frozenset({"equity", "etf", "sukuk", "cash", "other"})
MARKET_KEYS = frozenset({"us", "tr", "other", "unknown"})
ECONOMIC_EXPOSURE_KEYS = frozenset(
    {"equity", "fixed_income", "sukuk", "real_estate", "cash", "commodity", "other"}
)
CLASS_MAP = {
    ASSET_CLASS_EQUITY: "equity",
    ASSET_CLASS_ETF: "etf",
    ASSET_CLASS_SUKUK: "sukuk",
    "fixed_income": "sukuk",
    ASSET_CLASS_CASH: "cash",
}


class AllocationDimension(str, Enum):
    ASSET_CLASS = "ASSET_CLASS"
    MARKET = "MARKET"
    ECONOMIC_EXPOSURE = "ECONOMIC_EXPOSURE"


class AllocationCompleteness(str, Enum):
    COMPLETE_ALLOCATION = "COMPLETE_ALLOCATION"
    PARTIAL_ALLOCATION = "PARTIAL_ALLOCATION"
    OBSERVABLE_ALLOCATION = "OBSERVABLE_ALLOCATION"


class AllocationProvenance(str, Enum):
    USER_DEFINED = "USER_DEFINED"
    PRODUCT_POLICY = "PRODUCT_POLICY"
    NONE = "NONE"


class AllocationPolicyStatus(str, Enum):
    TARGET_NOT_CONFIGURED = "TARGET_NOT_CONFIGURED"
    CONFIGURED = "CONFIGURED"


class DriftStatus(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"
    UNDERWEIGHT = "UNDERWEIGHT"
    ON_TARGET = "ON_TARGET"
    INDETERMINATE = "INDETERMINATE"


class RoutingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INDETERMINATE = "INDETERMINATE"
    FX_REQUIRED = "FX_REQUIRED"
    TARGET_NOT_CONFIGURED = "TARGET_NOT_CONFIGURED"


class RoutingEvidenceQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AllocationTarget:
    bucket_id: str
    dimension: AllocationDimension
    target_weight_pct: float
    min_weight_pct: Optional[float] = None
    max_weight_pct: Optional[float] = None
    source: AllocationProvenance = AllocationProvenance.USER_DEFINED

    def validate(self) -> None:
        key = str(self.bucket_id or "").strip().lower()
        if not key:
            raise WealthValidationError("Hedef kova kimliği gerekli.")
        allowed = _allowed_target_keys(self.dimension)
        if key not in allowed:
            raise WealthValidationError(f"Geçersiz hedef kova: {self.bucket_id}")
        weight = float(self.target_weight_pct)
        if weight < 0 or weight > 100:
            raise WealthValidationError("Hedef ağırlık 0–100 aralığında olmalı.")
        if self.min_weight_pct is not None and float(self.min_weight_pct) < 0:
            raise WealthValidationError("Minimum ağırlık negatif olamaz.")
        if self.max_weight_pct is not None and float(self.max_weight_pct) > 100:
            raise WealthValidationError("Maksimum ağırlık 100'ü aşamaz.")
        if (
            self.min_weight_pct is not None
            and self.max_weight_pct is not None
            and float(self.min_weight_pct) > float(self.max_weight_pct)
        ):
            raise WealthValidationError("Minimum ağırlık maksimumdan büyük olamaz.")
        if self.min_weight_pct is not None and weight < float(self.min_weight_pct):
            raise WealthValidationError("Hedef ağırlık minimumun altında.")
        if self.max_weight_pct is not None and weight > float(self.max_weight_pct):
            raise WealthValidationError("Hedef ağırlık maksimumun üstünde.")


@dataclass(frozen=True)
class AllocationPolicy:
    targets: Tuple[AllocationTarget, ...] = ()
    tolerance_pct: float = ALLOCATION_DRIFT_TOLERANCE_PCT
    provenance: AllocationProvenance = AllocationProvenance.NONE

    def validate(self) -> None:
        if float(self.tolerance_pct) < 0:
            raise WealthValidationError("Sapma toleransı negatif olamaz.")
        if self.provenance == AllocationProvenance.NONE or not self.targets:
            return
        seen: set[Tuple[str, str]] = set()
        grouped: Dict[AllocationDimension, list[AllocationTarget]] = {}
        for target in self.targets:
            target.validate()
            key = (target.dimension.value, str(target.bucket_id).strip().lower())
            if key in seen:
                raise WealthValidationError("Aynı boyutta tekrarlanan hedef kova.")
            seen.add(key)
            grouped.setdefault(target.dimension, []).append(target)
        for dimension, rows in grouped.items():
            total = sum(float(row.target_weight_pct) for row in rows)
            if abs(total - 100.0) > TARGET_SUM_EPSILON_PCT:
                raise WealthValidationError(
                    f"{dimension.value} hedefleri ~100% toplamalı; mevcut {total:.4f}."
                )


@dataclass(frozen=True)
class UnresolvedHolding:
    symbol: str
    asset_class: str
    market: str
    reason: str


@dataclass(frozen=True)
class AllocationBucket:
    bucket_id: str
    dimension: AllocationDimension
    label: str
    observable_market_value: Optional[float]
    observable_weight_pct: Optional[float]
    weight_scope: AllocationCompleteness
    position_count: int
    symbols: Tuple[str, ...]
    unpriced_symbols: Tuple[str, ...]
    valuation_complete: bool
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DriftResult:
    bucket_id: str
    dimension: AllocationDimension
    observable_weight_pct: Optional[float]
    target_weight_pct: float
    drift_pct: Optional[float]
    status: DriftStatus
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ContributionRoutingResult:
    status: RoutingStatus
    dimension: Optional[AllocationDimension]
    best_bucket_id: Optional[str]
    before_drift_score: Optional[float]
    after_drift_score: Optional[float]
    improvement: Optional[float]
    evidence_quality: RoutingEvidenceQuality
    limitations: Tuple[str, ...] = ()
    candidates: Tuple[Tuple[str, float], ...] = ()


@dataclass(frozen=True)
class AllocationDecisionSignals:
    """Consumption surface for Portfolio Decision Intelligence."""

    target_status: AllocationPolicyStatus
    completeness: AllocationCompleteness
    material_drift: bool
    allocation_evidence_incomplete: bool
    contribution_routing_available: bool
    best_routing_bucket_id: Optional[str]
    limitations: Tuple[str, ...]
    unknown_exposure_symbols: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AllocationIntelligenceView:
    completeness: AllocationCompleteness
    observable_total_market_value: float
    base_currency: str
    unpriced_holdings: Tuple[UnresolvedHolding, ...]
    asset_class_buckets: Tuple[AllocationBucket, ...]
    market_buckets: Tuple[AllocationBucket, ...]
    target_policy_status: AllocationPolicyStatus
    provenance: AllocationProvenance
    drift: Tuple[DriftResult, ...]
    routing: Tuple[ContributionRoutingResult, ...]
    limitations: Tuple[str, ...]
    generated_from: Tuple[str, ...]
    signals: AllocationDecisionSignals
    unknown_exposure_symbols: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completeness": self.completeness.value,
            "observable_total_market_value": self.observable_total_market_value,
            "unpriced_holdings": [row.symbol for row in self.unpriced_holdings],
            "target_policy_status": self.target_policy_status.value,
            "drift_status": [row.status.value for row in self.drift],
            "routing_status": [row.status.value for row in self.routing],
            "limitations": list(self.limitations),
        }


def _round_weight(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), WEIGHT_QUANT)


def _allowed_target_keys(dimension: AllocationDimension) -> frozenset:
    if dimension == AllocationDimension.ASSET_CLASS:
        return ASSET_CLASS_KEYS
    if dimension == AllocationDimension.MARKET:
        return MARKET_KEYS
    if dimension == AllocationDimension.ECONOMIC_EXPOSURE:
        return ECONOMIC_EXPOSURE_KEYS
    raise WealthValidationError(f"Geçersiz hedef boyutu: {dimension}")


def policy_is_configured(policy: Optional[AllocationPolicy]) -> bool:
    return bool(
        policy is not None
        and policy.provenance != AllocationProvenance.NONE
        and policy.targets
    )


def _map_asset_class(raw: str, *, is_cash: bool) -> str:
    if is_cash:
        return "cash"
    key = CLASS_MAP.get(str(raw or "").strip().lower())
    return key or "other"


def _map_market(raw: Optional[str]) -> str:
    token = str(raw or "").strip().upper()
    if not token:
        return "unknown"
    if token in US_MARKET_ALIASES:
        return "us"
    if token in TR_MARKET_ALIASES:
        return "tr"
    if token in {"OTHER", "UNKNOWN"}:
        return token.lower()
    return "other"


def _known_market(symbol: str, currency: str) -> Optional[str]:
    sym = str(symbol or "").strip().upper()
    if sym not in KNOWN_MARKET_SYMBOLS:
        return None
    _cls, market, _kind, _status = resolve_asset_metadata(sym, currency=currency)
    return _map_market(market)


def _classify(
    row: PositionValuationRow,
    *,
    asset_by_id: Dict[str, Dict[str, Any]],
    asset_by_symbol: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    asset = asset_by_id.get(str(row.asset_id or "")) or asset_by_symbol.get(
        str(row.symbol or "").strip().upper()
    )
    asset_class = _map_asset_class(
        str((asset or {}).get("asset_class") or row.asset_class or ""),
        is_cash=bool(row.is_cash),
    )
    market_raw = (asset or {}).get("market")
    if market_raw:
        return asset_class, _map_market(str(market_raw))
    known = _known_market(row.symbol, row.valuation_currency)
    if known:
        return asset_class, known
    return asset_class, "unknown"


def _unvalued_position_row(position: Dict[str, Any], asset: Dict[str, Any]) -> PositionValuationRow:
    symbol = str(asset.get("symbol") or "").strip().upper()
    currency = normalize_currency(asset.get("currency"))
    quantity = float(position.get("quantity") or 0.0)
    average_cost = float(position.get("average_cost") or 0.0)
    return PositionValuationRow(
        position_id=str(position.get("id") or f"unvalued-{symbol}"),
        account_id=str(position.get("account_id") or ""),
        asset_id=str(position.get("asset_id") or ""),
        symbol=symbol,
        asset_class=str(asset.get("asset_class") or ""),
        account_name="",
        quantity=quantity,
        average_cost=average_cost,
        valuation_currency=currency,
        price=None,
        price_available=False,
        market_value=None,
        cost_basis=quantity * average_cost,
        unrealized_pl=None,
        weight_pct=None,
        is_cash=False,
        included_in_base_totals=False,
    )


def _recover_unvalued_rows(
    *,
    existing: Sequence[PositionValuationRow],
    positions: Optional[Sequence[dict]],
    asset_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[PositionValuationRow, ...]:
    seen = {
        str(row.symbol or "").strip().upper()
        for row in existing
        if str(row.symbol or "").strip()
    }
    recovered: list[PositionValuationRow] = []
    for position in positions or []:
        if float(position.get("quantity") or 0) <= 0:
            continue
        asset = asset_by_id.get(str(position.get("asset_id") or ""), {})
        symbol = str(asset.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        recovered.append(_unvalued_position_row(position, asset))
    return tuple(recovered)


def _all_rows(view: PortfolioIntelligenceView) -> Tuple[PositionValuationRow, ...]:
    seen: set[str] = set()
    rows: list[PositionValuationRow] = []
    for row in (
        list(view.priced_positions)
        + list(view.unpriced_positions)
        + list(view.foreign_currency_positions)
    ):
        key = row.position_id or f"{row.symbol}:{row.account_id}:{row.asset_id}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return tuple(rows)


def _is_observable(row: PositionValuationRow) -> bool:
    return bool(
        row.included_in_base_totals
        and row.price_available
        and row.market_value is not None
    )


def _bucket_label(dimension: AllocationDimension, bucket_id: str) -> str:
    labels = {
        "equity": "Equity",
        "etf": "ETF",
        "sukuk": "Sukuk",
        "cash": "Cash",
        "other": "Other",
        "us": "US",
        "tr": "TR",
        "unknown": "Unknown",
        "fixed_income": "Fixed income",
        "real_estate": "Real estate",
        "commodity": "Commodity",
    }
    if dimension == AllocationDimension.MARKET and bucket_id == "other":
        return "Other market"
    return labels.get(bucket_id, bucket_id)


def _build_buckets(
    rows: Sequence[Tuple[PositionValuationRow, str, str]],
    *,
    dimension: AllocationDimension,
    observable_total: float,
) -> Tuple[AllocationBucket, ...]:
    grouped: Dict[str, list[Tuple[PositionValuationRow, str, str]]] = {}
    for item in rows:
        row, asset_class, market = item
        key = asset_class if dimension == AllocationDimension.ASSET_CLASS else market
        grouped.setdefault(key, []).append(item)

    buckets: list[AllocationBucket] = []
    for key in sorted(grouped):
        items = grouped[key]
        symbols = tuple(
            dict.fromkeys(str(row.symbol or "").strip().upper() for row, *_ in items if row.symbol)
        )
        unpriced = tuple(
            dict.fromkeys(
                str(row.symbol or "").strip().upper()
                for row, *_ in items
                if row.symbol and not _is_observable(row)
            )
        )
        observable_mv = sum(float(row.market_value or 0.0) for row, *_ in items if _is_observable(row))
        has_observable = any(_is_observable(row) for row, *_ in items)
        weight = (
            (observable_mv / observable_total) * 100.0
            if has_observable and observable_total > 0
            else None
        )
        limitations = []
        if unpriced:
            limitations.append("PARTIAL_VALUATION")
            limitations.append("UNPRICED_HOLDINGS_EXCLUDED_FROM_WEIGHT")
        if has_observable:
            limitations.append("WEIGHTS_USE_PRICED_MV_ONLY")
        buckets.append(
            AllocationBucket(
                bucket_id=key,
                dimension=dimension,
                label=_bucket_label(dimension, key),
                observable_market_value=_round_weight(observable_mv) if has_observable else None,
                observable_weight_pct=_round_weight(weight),
                weight_scope=AllocationCompleteness.OBSERVABLE_ALLOCATION,
                position_count=len(items),
                symbols=symbols,
                unpriced_symbols=unpriced,
                valuation_complete=not unpriced,
                limitations=tuple(dict.fromkeys(limitations)),
            )
        )
    return tuple(buckets)


def _bucket_map(buckets: Sequence[AllocationBucket]) -> Dict[str, AllocationBucket]:
    return {row.bucket_id: row for row in buckets}


def _observable_weight(bucket: Optional[AllocationBucket]) -> Optional[float]:
    if bucket is None:
        return 0.0
    if bucket.observable_weight_pct is not None:
        return float(bucket.observable_weight_pct)
    if bucket.unpriced_symbols:
        return None
    return 0.0


def _drift_status(
    *,
    observable_weight: Optional[float],
    target_weight: float,
    tolerance: float,
    unpriced_in_bucket: bool,
    unpriced_outside: bool,
    valuation_complete: bool,
) -> Tuple[DriftStatus, Optional[float], Tuple[str, ...]]:
    if observable_weight is None:
        return DriftStatus.INDETERMINATE, None, ("PARTIAL_VALUATION",)
    drift = float(observable_weight) - float(target_weight)
    limitations: list[str] = []
    if valuation_complete:
        if abs(drift) <= tolerance:
            return DriftStatus.ON_TARGET, drift, ()
        status = DriftStatus.OVERWEIGHT if drift > 0 else DriftStatus.UNDERWEIGHT
        return status, drift, ()
    limitations.append("PARTIAL_VALUATION")
    limitations.append("OBSERVABLE_ALLOCATION_ONLY")
    if unpriced_in_bucket and unpriced_outside:
        return DriftStatus.INDETERMINATE, drift, tuple(limitations)
    if unpriced_in_bucket and not unpriced_outside:
        if drift > tolerance:
            return DriftStatus.OVERWEIGHT, drift, tuple(limitations)
        return DriftStatus.INDETERMINATE, drift, tuple(limitations)
    if unpriced_outside and not unpriced_in_bucket:
        if drift < -tolerance:
            return DriftStatus.UNDERWEIGHT, drift, tuple(limitations)
        return DriftStatus.INDETERMINATE, drift, tuple(limitations)
    return DriftStatus.INDETERMINATE, drift, tuple(limitations)


def _compute_drift(
    buckets: Sequence[AllocationBucket],
    targets: Sequence[AllocationTarget],
    *,
    tolerance: float,
    valuation_complete: bool,
) -> Tuple[DriftResult, ...]:
    by_id = _bucket_map(buckets)
    any_unpriced = any(bucket.unpriced_symbols for bucket in buckets)
    results: list[DriftResult] = []
    for target in sorted(targets, key=lambda row: row.bucket_id):
        bucket = by_id.get(target.bucket_id)
        unpriced_in = bool(bucket.unpriced_symbols) if bucket else False
        unpriced_out = any(
            other.unpriced_symbols for other in buckets if other.bucket_id != target.bucket_id
        ) or (any_unpriced and bucket is None)
        observable = _observable_weight(bucket)
        status, drift, limitations = _drift_status(
            observable_weight=observable,
            target_weight=float(target.target_weight_pct),
            tolerance=tolerance,
            unpriced_in_bucket=unpriced_in,
            unpriced_outside=unpriced_out,
            valuation_complete=valuation_complete,
        )
        results.append(
            DriftResult(
                bucket_id=target.bucket_id,
                dimension=target.dimension,
                observable_weight_pct=_round_weight(observable),
                target_weight_pct=float(target.target_weight_pct),
                drift_pct=_round_weight(drift),
                status=status,
                limitations=limitations,
            )
        )
    return tuple(results)


def _drift_score(
    weights: Dict[str, float],
    targets: Sequence[AllocationTarget],
) -> float:
    return sum(
        abs(float(weights.get(row.bucket_id, 0.0)) - float(row.target_weight_pct))
        for row in targets
    )


def _comparable_contribution(
    *,
    amount: Optional[Decimal],
    currency: Optional[str],
    base_currency: str,
    conversion: Optional[ConversionAssumption],
) -> Tuple[Optional[float], Tuple[str, ...], Optional[RoutingStatus]]:
    if amount is None:
        return None, (), RoutingStatus.UNAVAILABLE
    value = Decimal(str(amount))
    if value <= 0:
        return None, ("NON_POSITIVE_CONTRIBUTION",), RoutingStatus.UNAVAILABLE
    ccy = normalize_currency(currency or base_currency)
    base = normalize_currency(base_currency)
    if ccy == base:
        return float(value), (), None
    if conversion is None:
        return None, ("FX_CONVERSION_REQUIRED",), RoutingStatus.FX_REQUIRED
    from_ccy = normalize_currency(conversion.from_currency)
    to_ccy = normalize_currency(conversion.to_currency)
    if not (
        (from_ccy == ccy and to_ccy == base) or (from_ccy == base and to_ccy == ccy)
    ):
        return None, ("FX_CONVERSION_REQUIRED",), RoutingStatus.FX_REQUIRED
    converted = conversion.convert(value) if from_ccy == ccy else value * conversion.rate
    return float(converted), ("PLANNING_CONVERSION_USED",), None


def _route_dimension(
    buckets: Sequence[AllocationBucket],
    targets: Sequence[AllocationTarget],
    *,
    contribution: float,
    observable_total: float,
    valuation_complete: bool,
    extra_limitations: Sequence[str] = (),
) -> ContributionRoutingResult:
    dimension = targets[0].dimension
    current_weights = {
        row.bucket_id: float(row.observable_weight_pct or 0.0)
        for row in buckets
        if row.observable_weight_pct is not None
    }
    for target in targets:
        current_weights.setdefault(target.bucket_id, 0.0)
    before = _drift_score(current_weights, targets)
    new_total = observable_total + contribution
    candidates: list[Tuple[str, float]] = []
    for target in targets:
        weights: Dict[str, float] = {}
        for row in buckets:
            mv = float(row.observable_market_value or 0.0) if row.observable_weight_pct is not None else 0.0
            if row.bucket_id == target.bucket_id:
                mv += contribution
            weights[row.bucket_id] = (mv / new_total) * 100.0 if new_total > 0 else 0.0
        if target.bucket_id not in weights:
            weights[target.bucket_id] = (contribution / new_total) * 100.0 if new_total > 0 else 0.0
        after = _drift_score(weights, targets)
        candidates.append((target.bucket_id, after))
    candidates.sort(key=lambda item: (item[1], item[0]))
    best_id, after = candidates[0]
    improvement = before - after
    limitations = list(extra_limitations)
    if not valuation_complete:
        limitations.extend(("PARTIAL_VALUATION", "OBSERVABLE_ALLOCATION_ONLY"))
    if observable_total <= 0 and not valuation_complete:
        return ContributionRoutingResult(
            status=RoutingStatus.INDETERMINATE,
            dimension=dimension,
            best_bucket_id=None,
            before_drift_score=_round_weight(before),
            after_drift_score=None,
            improvement=None,
            evidence_quality=RoutingEvidenceQuality.UNAVAILABLE,
            limitations=tuple(dict.fromkeys(limitations + ["VALUATION_TOO_INCOMPLETE"])),
            candidates=tuple((bucket, round(score, WEIGHT_QUANT)) for bucket, score in candidates),
        )
    return ContributionRoutingResult(
        status=RoutingStatus.AVAILABLE,
        dimension=dimension,
        best_bucket_id=best_id,
        before_drift_score=_round_weight(before),
        after_drift_score=_round_weight(after),
        improvement=_round_weight(improvement),
        evidence_quality=(
            RoutingEvidenceQuality.COMPLETE
            if valuation_complete
            else RoutingEvidenceQuality.PARTIAL
        ),
        limitations=tuple(dict.fromkeys(limitations)),
        candidates=tuple((bucket, round(score, WEIGHT_QUANT)) for bucket, score in candidates),
    )


def allocation_decision_signals(view: AllocationIntelligenceView) -> AllocationDecisionSignals:
    routing_available = any(row.status == RoutingStatus.AVAILABLE for row in view.routing)
    best = next((row.best_bucket_id for row in view.routing if row.status == RoutingStatus.AVAILABLE), None)
    material = any(
        row.status in {DriftStatus.OVERWEIGHT, DriftStatus.UNDERWEIGHT} for row in view.drift
    )
    return AllocationDecisionSignals(
        target_status=view.target_policy_status,
        completeness=view.completeness,
        material_drift=material,
        allocation_evidence_incomplete=(
            view.completeness != AllocationCompleteness.COMPLETE_ALLOCATION
            or "EXPOSURE_CLASSIFICATION_INCOMPLETE" in view.limitations
        ),
        contribution_routing_available=routing_available,
        best_routing_bucket_id=best,
        limitations=view.limitations,
        unknown_exposure_symbols=view.unknown_exposure_symbols,
    )


def build_allocation_intelligence(
    portfolio_view: PortfolioIntelligenceView,
    *,
    policy: Optional[AllocationPolicy] = None,
    contribution_amount: Optional[Decimal] = None,
    contribution_currency: Optional[str] = None,
    conversion: Optional[ConversionAssumption] = None,
    assets: Optional[Sequence[dict]] = None,
    positions: Optional[Sequence[dict]] = None,
    exposure_buckets: Optional[Sequence[AllocationBucket]] = None,
) -> AllocationIntelligenceView:
    """Deterministic observable allocation, explicit-target drift, contribution-only routing."""
    if policy is not None:
        policy.validate()
    current = current_wealth_from_portfolio_view(
        portfolio_view,
        goal_currency=portfolio_view.base_currency or "USD",
        positions=positions,
        assets=assets,
    )
    asset_by_id = {str(row.get("id") or ""): row for row in (assets or [])}
    asset_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in (assets or [])
        if str(row.get("symbol") or "").strip()
    }
    view_rows = _all_rows(portfolio_view)
    recovered = _recover_unvalued_rows(
        existing=view_rows,
        positions=positions,
        asset_by_id=asset_by_id,
    )
    classified = tuple(
        (row, *_classify(row, asset_by_id=asset_by_id, asset_by_symbol=asset_by_symbol))
        for row in (*view_rows, *recovered)
    )
    observable_total = float(portfolio_view.priced_total_market_value or 0.0)
    completeness = (
        AllocationCompleteness.COMPLETE_ALLOCATION
        if current.valuation_complete
        else AllocationCompleteness.PARTIAL_ALLOCATION
    )
    asset_class_buckets = _build_buckets(
        classified,
        dimension=AllocationDimension.ASSET_CLASS,
        observable_total=observable_total,
    )
    market_buckets = _build_buckets(
        classified,
        dimension=AllocationDimension.MARKET,
        observable_total=observable_total,
    )
    unresolved = []
    seen = set()
    for row, asset_class, market in classified:
        if _is_observable(row):
            continue
        symbol = str(row.symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        reason = "FOREIGN_CURRENCY" if not row.included_in_base_totals else "UNPRICED"
        unresolved.append(
            UnresolvedHolding(
                symbol=symbol,
                asset_class=asset_class,
                market=market,
                reason=reason,
            )
        )
    limitations: list[str] = []
    if completeness != AllocationCompleteness.COMPLETE_ALLOCATION:
        limitations.append("PARTIAL_VALUATION")
        limitations.append("WEIGHTS_USE_PRICED_MV_ONLY")
        limitations.append("LOWER_BOUND_MARKET_VALUE")
    configured = policy_is_configured(policy)
    status = (
        AllocationPolicyStatus.CONFIGURED
        if configured
        else AllocationPolicyStatus.TARGET_NOT_CONFIGURED
    )
    provenance = policy.provenance if policy is not None else AllocationProvenance.NONE
    if not configured:
        limitations.append("TARGET_NOT_CONFIGURED")
    drift: Tuple[DriftResult, ...] = ()
    routing: Tuple[ContributionRoutingResult, ...] = ()
    if configured and policy is not None:
        tolerance = float(policy.tolerance_pct)
        by_dimension: Dict[AllocationDimension, list[AllocationTarget]] = {}
        for target in policy.targets:
            by_dimension.setdefault(target.dimension, []).append(target)
        drift_rows: list[DriftResult] = []
        routing_rows: list[ContributionRoutingResult] = []
        comparable, fx_notes, fx_status = _comparable_contribution(
            amount=contribution_amount,
            currency=contribution_currency,
            base_currency=portfolio_view.base_currency,
            conversion=conversion,
        )
        for dimension in (
            AllocationDimension.ASSET_CLASS,
            AllocationDimension.MARKET,
            AllocationDimension.ECONOMIC_EXPOSURE,
        ):
            targets = by_dimension.get(dimension) or []
            if not targets:
                continue
            unknown_priced = False
            extra_limits: Tuple[str, ...] = ()
            if dimension == AllocationDimension.ASSET_CLASS:
                buckets = asset_class_buckets
                complete = current.valuation_complete
            elif dimension == AllocationDimension.MARKET:
                buckets = market_buckets
                complete = current.valuation_complete
            else:
                buckets = tuple(exposure_buckets or ())
                if not buckets:
                    continue
                unknown = next((row for row in buckets if row.bucket_id == "unknown"), None)
                unknown_priced = bool(
                    unknown is not None
                    and unknown.symbols
                    and (unknown.observable_weight_pct or 0.0) > 0
                )
                complete = current.valuation_complete and not unknown_priced
                if unknown_priced:
                    extra_limits = ("EXPOSURE_CLASSIFICATION_INCOMPLETE",)
            computed = _compute_drift(
                buckets,
                targets,
                tolerance=tolerance,
                valuation_complete=complete,
            )
            if dimension == AllocationDimension.ECONOMIC_EXPOSURE and unknown_priced:
                safe: list[DriftResult] = []
                for row in computed:
                    if row.status in {DriftStatus.UNDERWEIGHT, DriftStatus.ON_TARGET}:
                        safe.append(
                            replace(
                                row,
                                status=DriftStatus.INDETERMINATE,
                                limitations=tuple(
                                    dict.fromkeys(
                                        (*row.limitations, "EXPOSURE_CLASSIFICATION_INCOMPLETE")
                                    )
                                ),
                            )
                        )
                    else:
                        safe.append(
                            replace(
                                row,
                                limitations=tuple(
                                    dict.fromkeys(
                                        (*row.limitations, "EXPOSURE_CLASSIFICATION_INCOMPLETE")
                                    )
                                ),
                            )
                        )
                computed = tuple(safe)
            drift_rows.extend(computed)
            if contribution_amount is None:
                routing_rows.append(
                    ContributionRoutingResult(
                        status=RoutingStatus.UNAVAILABLE,
                        dimension=dimension,
                        best_bucket_id=None,
                        before_drift_score=None,
                        after_drift_score=None,
                        improvement=None,
                        evidence_quality=RoutingEvidenceQuality.UNAVAILABLE,
                        limitations=("CONTRIBUTION_AMOUNT_REQUIRED",),
                    )
                )
            elif fx_status is not None:
                routing_rows.append(
                    ContributionRoutingResult(
                        status=fx_status,
                        dimension=dimension,
                        best_bucket_id=None,
                        before_drift_score=None,
                        after_drift_score=None,
                        improvement=None,
                        evidence_quality=RoutingEvidenceQuality.UNAVAILABLE,
                        limitations=fx_notes,
                    )
                )
            else:
                routed = _route_dimension(
                    buckets,
                    targets,
                    contribution=float(comparable or 0.0),
                    observable_total=observable_total,
                    valuation_complete=complete,
                    extra_limitations=tuple(dict.fromkeys((*fx_notes, *extra_limits))),
                )
                if unknown_priced and routed.status == RoutingStatus.AVAILABLE:
                    routed = replace(
                        routed,
                        status=RoutingStatus.INDETERMINATE,
                        best_bucket_id=None,
                        after_drift_score=None,
                        improvement=None,
                        evidence_quality=RoutingEvidenceQuality.PARTIAL,
                    )
                routing_rows.append(routed)
        drift = tuple(drift_rows)
        routing = tuple(routing_rows)
    else:
        routing = (
            ContributionRoutingResult(
                status=RoutingStatus.TARGET_NOT_CONFIGURED,
                dimension=None,
                best_bucket_id=None,
                before_drift_score=None,
                after_drift_score=None,
                improvement=None,
                evidence_quality=RoutingEvidenceQuality.UNAVAILABLE,
                limitations=("TARGET_NOT_CONFIGURED",),
            ),
        )
    generated_from = (
        "portfolio_intelligence_view",
        "current_wealth_from_portfolio_view",
        "wealth_asset_metadata",
        "ALLOCATION_DRIFT_TOLERANCE_PCT",
    )
    unknown_exposure_symbols: Tuple[str, ...] = ()
    if exposure_buckets:
        unknown_bucket = next((row for row in exposure_buckets if row.bucket_id == "unknown"), None)
        if unknown_bucket and unknown_bucket.symbols:
            unknown_exposure_symbols = unknown_bucket.symbols
            if (unknown_bucket.observable_weight_pct or 0.0) > 0:
                limitations.append("EXPOSURE_CLASSIFICATION_INCOMPLETE")
    notes = tuple(dict.fromkeys(limitations))
    exposure_incomplete = "EXPOSURE_CLASSIFICATION_INCOMPLETE" in notes
    signals = AllocationDecisionSignals(
        target_status=status,
        completeness=completeness,
        material_drift=any(
            row.status in {DriftStatus.OVERWEIGHT, DriftStatus.UNDERWEIGHT} for row in drift
        ),
        allocation_evidence_incomplete=(
            completeness != AllocationCompleteness.COMPLETE_ALLOCATION or exposure_incomplete
        ),
        contribution_routing_available=any(
            row.status == RoutingStatus.AVAILABLE for row in routing
        ),
        best_routing_bucket_id=next(
            (row.best_bucket_id for row in routing if row.status == RoutingStatus.AVAILABLE),
            None,
        ),
        limitations=notes,
        unknown_exposure_symbols=unknown_exposure_symbols,
    )
    return AllocationIntelligenceView(
        completeness=completeness,
        observable_total_market_value=observable_total,
        base_currency=str(portfolio_view.base_currency or "USD"),
        unpriced_holdings=tuple(unresolved),
        asset_class_buckets=asset_class_buckets,
        market_buckets=market_buckets,
        target_policy_status=status,
        provenance=provenance,
        drift=drift,
        routing=routing,
        limitations=notes,
        generated_from=generated_from,
        signals=signals,
        unknown_exposure_symbols=unknown_exposure_symbols,
    )
