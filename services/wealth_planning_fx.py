from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from repositories.wealth_planning_fx_repository import WealthPlanningFxRepository
from services.wealth_contract import WealthValidationError
from services.wealth_goal_models import ConversionAssumption, quantize_money

PLANNING_FX_PROVENANCE = "USER_DEFINED"
PLANNING_FX_NONE_COPY = "TRY→USD projeksiyonu için kur varsayımları gerekli."
PLANNING_FX_DISCLAIMER = (
    "Bu değerler piyasa tahmini değil, uzun vadeli planlama varsayımlarıdır."
)
USDTRY_LABEL = "USDTRY"
USDTRY_HELP = "1 USD = ? TRY"
PROPOSED_PLANNING_FX_STATUS = "PROPOSED / NOT SAVED"
EXTENDED_PLANNING_FX_YEARS = (2032, 2033, 2034, 2035, 2036)
CONTINUATION_ANCHOR_YEARS = (2029, 2030, 2031)
PLANNING_FX_CONTINUATION_METHOD = (
    "Arithmetic continuation of the approved 2029–2031 USER_DEFINED path "
    "(mean year-over-year USDTRY increment). Planning-only; not a forecast; not saved."
)


class PlanningFxCompleteness(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class PlanningFxRate:
    year: int
    usdtry: Decimal
    provenance: str = PLANNING_FX_PROVENANCE

    def conversion(self, *, from_currency: str, to_currency: str) -> ConversionAssumption:
        return ConversionAssumption(from_currency, to_currency, self.usdtry)


@dataclass(frozen=True)
class PlanningFxSchedule:
    rates: Tuple[PlanningFxRate, ...] = ()

    def by_year(self) -> Dict[int, PlanningFxRate]:
        return {row.year: row for row in self.rates}

    def usdtry_for_year(self, year: int) -> Optional[Decimal]:
        row = self.by_year().get(int(year))
        return None if row is None else row.usdtry

    def missing_years(self, required: Sequence[int]) -> Tuple[int, ...]:
        present = set(self.by_year())
        return tuple(year for year in required if year not in present)

    def completeness(
        self,
        *,
        as_of: date,
        target_date: date,
        contribution_currency: str,
        goal_currency: str,
    ) -> PlanningFxCompleteness:
        if contribution_currency.strip().upper() == goal_currency.strip().upper():
            return PlanningFxCompleteness.NOT_REQUIRED
        required = required_planning_fx_years(as_of, target_date)
        if not required:
            return PlanningFxCompleteness.COMPLETE
        missing = self.missing_years(required)
        if len(missing) == len(required):
            return PlanningFxCompleteness.NONE
        if missing:
            return PlanningFxCompleteness.PARTIAL
        return PlanningFxCompleteness.COMPLETE

    def is_complete(
        self,
        *,
        as_of: date,
        target_date: date,
        contribution_currency: str,
        goal_currency: str,
    ) -> bool:
        status = self.completeness(
            as_of=as_of,
            target_date=target_date,
            contribution_currency=contribution_currency,
            goal_currency=goal_currency,
        )
        return status in {
            PlanningFxCompleteness.COMPLETE,
            PlanningFxCompleteness.NOT_REQUIRED,
        }


def required_planning_fx_years(as_of: date, target_date: date) -> Tuple[int, ...]:
    start = as_of.year
    end = target_date.year
    if end < start:
        return ()
    return tuple(range(start, end + 1))


def parse_usdtry_assumption(value: Any) -> Decimal:
    """USDTRY = TRY required for 1 USD. Rejects zero, negative, NaN, infinity."""
    if value is None:
        raise WealthValidationError("USDTRY varsayımı gerekli.")
    if isinstance(value, bool):
        raise WealthValidationError("USDTRY varsayımı sayısal olmalı.")
    if isinstance(value, float) and not math.isfinite(value):
        raise WealthValidationError("USDTRY varsayımı sonlu olmalı.")
    text = str(value).strip()
    if not text:
        raise WealthValidationError("USDTRY varsayımı gerekli.")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WealthValidationError("USDTRY varsayımı sayısal olmalı.") from exc
    if not parsed.is_finite():
        raise WealthValidationError("USDTRY varsayımı sonlu olmalı.")
    if parsed <= 0:
        raise WealthValidationError("USDTRY varsayımı sıfırdan büyük olmalı.")
    return parsed


def usd_from_try(try_amount: Decimal, usdtry: Decimal) -> Decimal:
    """TRY / USDTRY = USD. Never multiply."""
    rate = parse_usdtry_assumption(usdtry)
    return Decimal(str(try_amount)) / rate


def conversion_for_year(
    schedule: Optional[PlanningFxSchedule],
    *,
    year: int,
    contribution_currency: str,
    goal_currency: str,
) -> Optional[ConversionAssumption]:
    if schedule is None:
        return None
    rate = schedule.usdtry_for_year(year)
    if rate is None:
        return None
    return ConversionAssumption(
        contribution_currency.strip().upper(),
        goal_currency.strip().upper(),
        rate,
    )


def schedule_from_mapping(values: Mapping[int, Any]) -> PlanningFxSchedule:
    rates = []
    for year, raw in sorted(values.items()):
        rates.append(
            PlanningFxRate(
                year=int(year),
                usdtry=parse_usdtry_assumption(raw),
                provenance=PLANNING_FX_PROVENANCE,
            )
        )
    return PlanningFxSchedule(rates=tuple(rates))


def schedule_from_rows(rows: Iterable[Dict[str, Any]]) -> PlanningFxSchedule:
    rates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            year = int(row.get("year"))
            usdtry = parse_usdtry_assumption(row.get("usdtry"))
        except (TypeError, ValueError, WealthValidationError):
            continue
        provenance = str(row.get("provenance") or PLANNING_FX_PROVENANCE)
        if provenance != PLANNING_FX_PROVENANCE:
            continue
        rates.append(PlanningFxRate(year=year, usdtry=usdtry, provenance=provenance))
    return PlanningFxSchedule(rates=tuple(sorted(rates, key=lambda item: item.year)))


def load_planning_fx_schedule(wealth, portfolio_id: Optional[str]) -> PlanningFxSchedule:
    if wealth is None or not str(portfolio_id or "").strip():
        return PlanningFxSchedule()
    client = getattr(wealth, "client", None)
    user_id = str(getattr(wealth, "user_id", "") or "")
    if client is None or not user_id:
        return PlanningFxSchedule()
    try:
        rows = WealthPlanningFxRepository(client).list_for_portfolio(
            user_id, str(portfolio_id)
        )
    except Exception:
        return PlanningFxSchedule()
    if not isinstance(rows, (list, tuple)):
        return PlanningFxSchedule()
    return schedule_from_rows(rows)


def save_planning_fx_schedule(
    wealth,
    *,
    portfolio_id: str,
    values: Mapping[int, Any],
) -> PlanningFxSchedule:
    schedule = schedule_from_mapping(values)
    WealthPlanningFxRepository(wealth.client).replace_schedule(
        user_id=str(wealth.user_id),
        portfolio_id=str(portfolio_id),
        rows=[
            {"year": row.year, "usdtry": row.usdtry, "provenance": row.provenance}
            for row in schedule.rates
        ],
    )
    return schedule


def persist_additional_planning_fx_years(
    wealth,
    *,
    portfolio_id: str,
    values: Mapping[int, Any],
) -> Tuple[PlanningFxSchedule, int]:
    """Persist newly approved years only. Existing years cannot change."""
    incoming = schedule_from_mapping(values)
    current = load_planning_fx_schedule(wealth, portfolio_id)
    for row in incoming.rates:
        existing = current.usdtry_for_year(row.year)
        if existing is not None and existing != row.usdtry:
            raise WealthValidationError(
                f"{row.year} planlama kuru zaten {existing} ve değiştirilemez."
            )
    absent = [row for row in incoming.rates if current.usdtry_for_year(row.year) is None]
    inserted = 0
    if absent:
        written = WealthPlanningFxRepository(wealth.client).insert_absent_years(
            user_id=str(wealth.user_id),
            portfolio_id=str(portfolio_id),
            rows=[
                {"year": row.year, "usdtry": row.usdtry, "provenance": row.provenance}
                for row in absent
            ],
        )
        inserted = len(written)
    return load_planning_fx_schedule(wealth, portfolio_id), inserted


def missing_years_copy(years: Sequence[int]) -> str:
    if not years:
        return PLANNING_FX_NONE_COPY
    labeled = ", ".join(str(year) for year in years)
    return f"Eksik kur varsayımları: {labeled}"


@dataclass(frozen=True)
class ProposedPlanningFxYear:
    year: int
    proposed_usdtry: Decimal
    implied_annual_change_pct: Decimal
    status: str = PROPOSED_PLANNING_FX_STATUS


@dataclass(frozen=True)
class PlanningFxContinuationProposal:
    anchor_years: Tuple[int, ...]
    observed_usdtry: Tuple[Tuple[int, Decimal], ...]
    observed_increments: Tuple[Decimal, ...]
    observed_change_pct: Tuple[Decimal, ...]
    continuation_increment: Decimal
    through_year: int
    method: str
    status: str
    years: Tuple[ProposedPlanningFxYear, ...]

    def as_mapping(self) -> Dict[int, Decimal]:
        return {row.year: row.proposed_usdtry for row in self.years}


def propose_planning_fx_continuation(
    schedule: PlanningFxSchedule,
    *,
    anchor_years: Sequence[int] = CONTINUATION_ANCHOR_YEARS,
    through_year: int = EXTENDED_PLANNING_FX_YEARS[-1],
) -> PlanningFxContinuationProposal:
    """Build a planning-only 2032+ USDTRY continuation. Does not persist or forecast."""
    anchors = tuple(int(year) for year in anchor_years)
    if len(anchors) < 2:
        raise WealthValidationError("Devam varsayımı için en az iki çapa yılı gerekli.")
    by_year = schedule.by_year()
    missing_anchors = tuple(year for year in anchors if year not in by_year)
    if missing_anchors:
        labeled = ", ".join(str(year) for year in missing_anchors)
        raise WealthValidationError(f"Devam varsayımı için eksik çapa yılları: {labeled}")

    observed = tuple((year, by_year[year].usdtry) for year in anchors)
    increments: list[Decimal] = []
    change_pcts: list[Decimal] = []
    for previous, current in zip(anchors, anchors[1:]):
        prior_rate = by_year[previous].usdtry
        next_rate = by_year[current].usdtry
        delta = next_rate - prior_rate
        increments.append(delta)
        if prior_rate <= 0:
            raise WealthValidationError("USDTRY varsayımı sıfırdan büyük olmalı.")
        change_pcts.append(quantize_money((delta / prior_rate) * Decimal("100")))
    continuation = sum(increments, Decimal("0")) / Decimal(len(increments))
    last_year = anchors[-1]
    last_rate = by_year[last_year].usdtry
    proposed: list[ProposedPlanningFxYear] = []
    cursor = last_rate
    for year in range(last_year + 1, int(through_year) + 1):
        prior = cursor
        cursor = cursor + continuation
        implied = quantize_money((continuation / prior) * Decimal("100")) if prior > 0 else Decimal("0")
        proposed.append(
            ProposedPlanningFxYear(
                year=year,
                proposed_usdtry=parse_usdtry_assumption(cursor),
                implied_annual_change_pct=implied,
            )
        )
    return PlanningFxContinuationProposal(
        anchor_years=anchors,
        observed_usdtry=observed,
        observed_increments=tuple(increments),
        observed_change_pct=tuple(change_pcts),
        continuation_increment=continuation,
        through_year=int(through_year),
        method=PLANNING_FX_CONTINUATION_METHOD,
        status=PROPOSED_PLANNING_FX_STATUS,
        years=tuple(proposed),
    )
