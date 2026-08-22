from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_contract import WealthValidationError

MONEY_QUANT = Decimal("0.01")
RATE_ZERO = Decimal("0")

DEFAULT_TARGET_AMOUNT_USD = Decimal("500000")
DEFAULT_TARGET_DATE = date(2031, 12, 31)
DEFAULT_STARTING_MONTHLY_CONTRIBUTION = Decimal("60000")
DEFAULT_CONTRIBUTION_CURRENCY = "TRY"
DEFAULT_ANNUAL_CONTRIBUTION_INCREASE = Decimal("0.25")

COMPOUNDING_CONVENTION = (
    "Monthly compounding from an annual nominal rate: monthly_rate = annual_rate / 12. "
    "End-of-month contributions: each step compounds the existing balance first, then "
    "adds the contribution, which does not earn that period's return. "
    "Steps are calendar month-ends strictly after as_of through the target date. "
    "If as_of is mid-month, the first step pro-rates compounding by "
    "(month_end - as_of).days / days_in_that_month."
)


class GoalEvidenceStatus(str, Enum):
    REACHED = "REACHED"
    PROJECTED_TO_REACH = "PROJECTED_TO_REACH"
    PROJECTED_SHORTFALL = "PROJECTED_SHORTFALL"
    INDETERMINATE = "INDETERMINATE"


class ProjectionLimitation(str, Enum):
    PARTIAL_VALUATION = "PARTIAL_VALUATION"
    FX_CONVERSION_REQUIRED = "FX_CONVERSION_REQUIRED"
    CONTRIBUTION_CURRENCY_MISMATCH = "CONTRIBUTION_CURRENCY_MISMATCH"
    BASE_CURRENCY_MISMATCH = "BASE_CURRENCY_MISMATCH"


@dataclass(frozen=True)
class WealthGoal:
    """Long-term wealth target. Defaults are the 2031 plan; fields are editable later."""

    name: str
    target_amount: Decimal
    target_date: date
    currency: str = "USD"

    def validate(self) -> None:
        if self.target_amount <= 0:
            raise WealthValidationError("Hedef tutar sıfırdan büyük olmalı.")
        if self.target_date.year < 1900:
            raise WealthValidationError("Hedef tarihi geçersiz.")
        if not str(self.currency or "").strip():
            raise WealthValidationError("Hedef para birimi gerekli.")


@dataclass(frozen=True)
class ContributionPlan:
    """Recurring contribution schedule. Amounts stay in `currency` until converted."""

    starting_monthly: Decimal
    currency: str
    annual_increase_rate: Decimal = RATE_ZERO

    def validate(self) -> None:
        if self.starting_monthly < 0:
            raise WealthValidationError("Aylık katkı negatif olamaz.")
        if self.annual_increase_rate <= Decimal("-1"):
            raise WealthValidationError("Yıllık katkı artışı -100% veya daha düşük olamaz.")
        if not str(self.currency or "").strip():
            raise WealthValidationError("Katkı para birimi gerekli.")


@dataclass(frozen=True)
class ReturnScenario:
    """Planning assumption, not a forecast. `annual_rate` is nominal."""

    name: str
    annual_rate: Decimal

    @property
    def monthly_rate(self) -> Decimal:
        return self.annual_rate / Decimal(12)


@dataclass(frozen=True)
class ConversionAssumption:
    """Evidence for converting contribution currency into the goal currency.

    `rate` is units of `from_currency` per 1 unit of `to_currency`.
    Example: TRY→USD at 34 means 34 TRY per 1 USD; USD = TRY / 34.
    Absent when contribution currency already matches the goal.
    """

    from_currency: str
    to_currency: str
    rate: Decimal

    def validate(self) -> None:
        if self.rate <= 0:
            raise WealthValidationError("Kur varsayımı sıfırdan büyük olmalı.")
        if not str(self.from_currency or "").strip() or not str(self.to_currency or "").strip():
            raise WealthValidationError("Kur varsayımı para birimleri gerekli.")

    def convert(self, amount: Decimal) -> Decimal:
        self.validate()
        return amount / self.rate


@dataclass(frozen=True)
class CurrentWealthSnapshot:
    """Lower-bound measurable wealth. Unpriced holdings are listed, never zeroed."""

    currency: str
    current_value_lower_bound: Decimal
    valuation_complete: bool
    unvalued_symbols: Tuple[str, ...] = ()
    missing_price_symbols: Tuple[str, ...] = ()
    missing_fx_symbols: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionResult:
    scenario_name: str
    annual_rate: Decimal
    as_of_date: date
    target_date: date
    target_amount: Decimal
    current_value_lower_bound: Decimal
    measurable_gap: Decimal
    progress_pct_lower_bound: Decimal
    month_count: int
    projected_target_date_value: Optional[Decimal]
    projected_goal_reached: Optional[bool]
    projected_goal_reach_date: Optional[date]
    total_projected_contributions: Optional[Decimal]
    projected_investment_growth: Optional[Decimal]
    valuation_complete: bool
    projection_complete: bool
    status: GoalEvidenceStatus
    limitations: Tuple[ProjectionLimitation, ...]
    compounding_convention: str = COMPOUNDING_CONVENTION


def default_wealth_goal_2031() -> WealthGoal:
    return WealthGoal(
        name="Wealth OS 2031",
        target_amount=DEFAULT_TARGET_AMOUNT_USD,
        target_date=DEFAULT_TARGET_DATE,
        currency="USD",
    )


def default_contribution_plan() -> ContributionPlan:
    return ContributionPlan(
        starting_monthly=DEFAULT_STARTING_MONTHLY_CONTRIBUTION,
        currency=DEFAULT_CONTRIBUTION_CURRENCY,
        annual_increase_rate=DEFAULT_ANNUAL_CONTRIBUTION_INCREASE,
    )


def default_return_scenarios() -> Tuple[ReturnScenario, ...]:
    return (
        ReturnScenario("Conservative", Decimal("0.06")),
        ReturnScenario("Base", Decimal("0.08")),
        ReturnScenario("Growth", Decimal("0.10")),
    )


def current_wealth_from_portfolio_view(
    view: PortfolioIntelligenceView,
    *,
    goal_currency: str = "USD",
    positions: Optional[Sequence[dict]] = None,
    assets: Optional[Sequence[dict]] = None,
) -> CurrentWealthSnapshot:
    """Map existing PI valuation output. Does not reprice or treat missing MV as 0."""
    missing_price: list[str] = []
    missing_fx: list[str] = []
    seen_price: set[str] = set()
    seen_fx: set[str] = set()
    seen: set[str] = set()

    def _add(bucket: list[str], seen_bucket: set[str], symbol: str) -> None:
        if symbol in seen_bucket:
            return
        seen_bucket.add(symbol)
        bucket.append(symbol)
        seen.add(symbol)

    for row in list(view.unpriced_positions) + list(view.foreign_currency_positions):
        if row.included_in_base_totals and row.price_available:
            continue
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            continue
        if not row.price_available:
            _add(missing_price, seen_price, symbol)
        if row.fx_unavailable:
            _add(missing_fx, seen_fx, symbol)
        elif row.price_available and not row.included_in_base_totals:
            _add(missing_fx, seen_fx, symbol)

    priced_symbols = {
        str(row.symbol or "").strip().upper()
        for row in view.priced_positions
        if row.price_available and row.included_in_base_totals
    }
    asset_by_id = {str(row.get("id") or ""): row for row in (assets or [])}
    for position in positions or []:
        qty = float(position.get("quantity") or 0)
        if qty <= 0:
            continue
        asset = asset_by_id.get(str(position.get("asset_id") or ""), {})
        symbol = str(asset.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen or symbol in priced_symbols:
            continue
        _add(missing_price, seen_price, symbol)

    unvalued = list(dict.fromkeys([*missing_price, *missing_fx]))
    base = str(view.base_currency or "").strip().upper()
    goal_ccy = str(goal_currency or "").strip().upper()
    complete = (
        view.unpriced_position_count == 0
        and view.foreign_currency_position_count == 0
        and not view.mixed_currency_warning
        and base == goal_ccy
        and not unvalued
    )
    lower_bound = Decimal(str(view.priced_total_market_value or 0))
    snapshot_currency = base or goal_ccy
    return CurrentWealthSnapshot(
        currency=snapshot_currency,
        current_value_lower_bound=lower_bound,
        valuation_complete=complete,
        unvalued_symbols=tuple(unvalued),
        missing_price_symbols=tuple(missing_price),
        missing_fx_symbols=tuple(missing_fx),
    )


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)
