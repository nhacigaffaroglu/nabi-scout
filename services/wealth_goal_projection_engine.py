from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple


@dataclass(frozen=True)
class GoalProjectionScenario:
    label: str
    annual_return_assumption_pct: float
    projected_value: Optional[float]
    funding_gap: Optional[float]
    progress_pct: Optional[float]
    required_monthly_contribution: Optional[float]
    assumptions_note: str


@dataclass(frozen=True)
class GoalProjectionResult:
    goal_title: str
    target_value: Optional[float]
    target_date: Optional[str]
    current_value: Optional[float]
    currency: str
    monthly_contribution_assumption: float
    base_expected_return_pct: float
    scenarios: Tuple[GoalProjectionScenario, ...]
    limitations: Tuple[str, ...]


def _months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def _future_value(
    *,
    present_value: float,
    monthly_contribution: float,
    annual_return_pct: float,
    months: int,
) -> Optional[float]:
    if months <= 0:
        return present_value
    monthly_rate = annual_return_pct / 100.0 / 12.0
    if abs(monthly_rate) < 1e-12:
        return present_value + (monthly_contribution * months)
    growth = (1.0 + monthly_rate) ** months
    contribution_future = (
        monthly_contribution * ((growth - 1.0) / monthly_rate)
        if monthly_contribution
        else 0.0
    )
    return present_value * growth + contribution_future


def _required_monthly_contribution(
    *,
    present_value: float,
    target_value: float,
    annual_return_pct: float,
    months: int,
) -> Optional[float]:
    if months <= 0 or target_value <= present_value:
        return 0.0
    gap = target_value - present_value
    monthly_rate = annual_return_pct / 100.0 / 12.0
    if abs(monthly_rate) < 1e-12:
        return gap / months
    growth = (1.0 + monthly_rate) ** months
    annuity_factor = (growth - 1.0) / monthly_rate
    if abs(annuity_factor) < 1e-12:
        return None
    adjusted_gap = target_value - present_value * growth
    return adjusted_gap / annuity_factor


def project_goal(
    *,
    goal_title: str,
    target_value: Optional[float],
    target_date: Optional[str],
    current_value: Optional[float],
    currency: str,
    monthly_contribution_assumption: Optional[float] = None,
    expected_annual_return_assumption: Optional[float] = None,
) -> GoalProjectionResult:
    limitations: list[str] = []
    monthly = float(monthly_contribution_assumption or 0.0)
    base_return = float(expected_annual_return_assumption if expected_annual_return_assumption is not None else 7.0)

    if current_value is None:
        limitations.append("Mevcut portföy değeri hesaplanamadı.")
        current = 0.0
    else:
        current = float(current_value)

    months = 0
    if target_date:
        try:
            end = date.fromisoformat(str(target_date)[:10])
            months = _months_between(date.today(), end)
        except ValueError:
            limitations.append("Geçersiz hedef tarihi.")
    else:
        limitations.append("Hedef tarihi belirtilmedi; projeksiyon süresi varsayılan 60 ay.")

    if months <= 0 and not limitations:
        months = 60 if not target_date else 0

    scenario_returns = (
        ("Muhafazakâr", base_return - 3.0),
        ("Baz", base_return),
        ("İyimser", base_return + 3.0),
    )
    scenarios: list[GoalProjectionScenario] = []
    for label, ret in scenario_returns:
        projected = _future_value(
            present_value=current,
            monthly_contribution=monthly,
            annual_return_pct=ret,
            months=months or 60,
        )
        gap = None
        progress = None
        required_monthly = None
        if target_value is not None and projected is not None:
            gap = float(target_value) - projected
            if float(target_value) > 0:
                progress = min(100.0, (current / float(target_value)) * 100.0)
            if gap > 0 and months > 0:
                required_monthly = _required_monthly_contribution(
                    present_value=current,
                    target_value=float(target_value),
                    annual_return_pct=ret,
                    months=months,
                )
        scenarios.append(
            GoalProjectionScenario(
                label=label,
                annual_return_assumption_pct=ret,
                projected_value=projected,
                funding_gap=gap,
                progress_pct=progress,
                required_monthly_contribution=required_monthly,
                assumptions_note="Kullanıcı varsayımı; NABI tahmini değildir.",
            )
        )

    return GoalProjectionResult(
        goal_title=goal_title,
        target_value=target_value,
        target_date=target_date,
        current_value=current_value,
        currency=currency,
        monthly_contribution_assumption=monthly,
        base_expected_return_pct=base_return,
        scenarios=tuple(scenarios),
        limitations=tuple(limitations),
    )
