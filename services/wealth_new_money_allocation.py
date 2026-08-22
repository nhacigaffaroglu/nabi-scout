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

from services.portfolio_allocation_intelligence import (
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
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
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
    return str(value or "").strip().upper() == BLOCKING_PARTICIPATION


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
) -> AllocationPlan:
    """Return a proposed plan only. Never writes or fetches."""
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

    intelligence = allocation or build_allocation_intelligence(
        portfolio_view,
        policy=policy,
        contribution_amount=amount,
        contribution_currency=currency,
        conversion=conversion,
        assets=assets,
        positions=positions,
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
    existing_secs: list[_Security] = []
    for row in _existing_positions(portfolio_view):
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            continue
        asset_class, market = _classify(
            row, asset_by_id=asset_by_id, asset_by_symbol=asset_by_symbol
        )
        layer = _layer_of(dimension=dimension, asset_class=asset_class, market=market)
        if layer is None:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Katman sınıflandırılamadı.")
            )
            continue
        if layer in overweight:
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_OVERWEIGHT_LAYER,
                    f"{layer} katmanı hedefte veya üzerinde; yeni para varsayılan olarak eklenmez.",
                )
            )
            continue
        price = _valid_price(row.price) if row.price_available else None
        if price is None:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Mevcut fiyat yok veya geçersiz.")
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

    new_secs: list[_Security] = []
    for raw in candidates:
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol or symbol in held:
            continue
        decision = _norm_decision(raw.get("decision"))
        if not is_actionable_new_decision(decision):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_NOT_ACTIONABLE,
                    "Yeni fırsat için karar GÜÇLÜ ADAY veya ADAY değil.",
                )
            )
            continue
        if _participation_blocked(raw.get("participation_status")):
            skipped.append(
                AllocationSkip(
                    symbol,
                    REASON_PARTICIPATION_BLOCKED,
                    "Katılım durumu yeni fırsat tahsisini engelliyor.",
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
        layer = _layer_of(dimension=dimension, asset_class=asset_class, market=market)
        if layer is None:
            skipped.append(
                AllocationSkip(symbol, REASON_DATA_INCOMPLETE, "Yeni fırsat katmanı belirsiz.")
            )
            continue
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
                decision=decision,
                price=price,
                price_currency=normalize_currency(raw.get("currency") or currency),
                asset_class=asset_class,
                whole_share=_whole_share_required(asset_class),
            )
        )

    by_layer: Dict[str, list[_Security]] = {}
    for sec in existing_secs + new_secs:
        by_layer.setdefault(sec.layer, []).append(sec)

    remaining = amount
    total_value = Decimal(str(intelligence.observable_total_market_value or 0))
    recs: Dict[str, AllocationRecommendation] = {}

    def _unit_cost(sec: _Security) -> Optional[Decimal]:
        converted = _convert(
            sec.price,
            from_currency=sec.price_currency,
            to_currency=currency,
            conversion=conversion,
        )
        return converted

    def _add(sec: _Security, quantity: Decimal, spent: Decimal) -> None:
        nonlocal remaining, total_value
        remaining -= spent
        total_value += spent
        bucket_value[sec.layer] = bucket_value.get(sec.layer, Decimal("0")) + spent
        prior = recs.get(sec.symbol)
        if prior is None:
            if sec.existing:
                code, text = REASON_EXISTING_HOLDING_TOPUP, "Mevcut pozisyon, açık katmanda tamamlanır."
            elif sec.decision == "GÜÇLÜ ADAY":
                code, text = REASON_STRONG_CANDIDATE, "GÜÇLÜ ADAY, açık katmana yeni fırsat olarak eklenir."
            else:
                code, text = REASON_CANDIDATE, "ADAY, açık katmana yeni fırsat olarak eklenir."
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
                reason_text=f"{text} ({REASON_LAYER_DEFICIT}: {sec.layer})",
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
        current_b = bucket_value.get(layer, Decimal("0"))
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
        spent = qty * unit + fee
        if spent > remaining or spent > need:
            if sec.whole_share:
                skipped.append(
                    AllocationSkip(
                        sec.symbol,
                        REASON_INSUFFICIENT_CASH,
                        "Tam pay için nakit yetmiyor.",
                    )
                )
            return False
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
        budget = min(remaining, _needed(sec.layer)) - fee
        if budget <= 0:
            return Decimal("0")
        raw = budget / unit
        if sec.whole_share:
            return Decimal(raw.to_integral_value(rounding=ROUND_DOWN))
        return raw

    for drift in underweight:
        layer = drift.bucket_id
        securities = by_layer.get(layer, ())
        existing = sorted((row for row in securities if row.existing), key=lambda row: row.symbol)
        newcomers = sorted(
            (row for row in securities if not row.existing),
            key=lambda row: (DECISION_RANK.get(row.decision or "", 99), row.symbol),
        )
        progressed = True
        while progressed and remaining > 0 and _needed(layer) > 0:
            progressed = False
            for sec in existing:
                qty = Decimal("1") if sec.whole_share else _max_qty(sec)
                if qty > 0 and _try_buy(sec, qty=qty):
                    progressed = True
                if remaining <= 0 or _needed(layer) <= 0:
                    break
        for sec in newcomers:
            qty = _max_qty(sec)
            if qty > 0:
                _try_buy(sec, qty=qty)
            elif sec.whole_share and _unit_cost(sec) is not None:
                skipped.append(
                    AllocationSkip(
                        sec.symbol,
                        REASON_INSUFFICIENT_CASH,
                        "Tam pay için nakit yetmiyor.",
                    )
                )
            if remaining <= 0:
                break

    total_allocated = sum((row.allocated_amount for row in recs.values()), Decimal("0"))
    if total_allocated > amount:
        total_allocated = amount
    residual = amount - total_allocated
    if residual < 0:
        residual = Decimal("0")
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
    )
