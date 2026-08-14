from __future__ import annotations

from typing import Optional

from repositories.wealth_adviser_goal_repository import WealthAdviserGoalRepository
from repositories.wealth_investor_profile_repository import WealthInvestorProfileRepository
from services.wealth_adviser_profile_contract import (
    AdviserGoal,
    ConcentrationPreference,
    ExperienceLevel,
    GoalType,
    IncomeNeed,
    InvestmentHorizon,
    InvestorProfile,
    LiquidityNeed,
    RiskPreference,
)


class WealthAdviserProfileService:
    def __init__(self, client, user_id: str) -> None:
        self.user_id = user_id
        self._repo = WealthInvestorProfileRepository(client)

    def load_profile(self) -> InvestorProfile:
        row = self._repo.get_for_user(self.user_id)
        if not row:
            return InvestorProfile.empty(self.user_id)
        return InvestorProfile.from_row(row)

    def save_profile(
        self,
        *,
        investment_horizon: Optional[str] = None,
        risk_preference: Optional[str] = None,
        liquidity_need: Optional[str] = None,
        cash_preference: Optional[str] = None,
        concentration_preference: Optional[str] = None,
        income_need: Optional[str] = None,
        experience_level: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> InvestorProfile:
        current = self.load_profile()
        profile = InvestorProfile(
            user_id=self.user_id,
            profile_version=current.profile_version,
            investment_horizon=investment_horizon or None,
            risk_preference=risk_preference or None,
            liquidity_need=liquidity_need or None,
            cash_preference=cash_preference or None,
            concentration_preference=concentration_preference or None,
            income_need=income_need or None,
            experience_level=experience_level or None,
            notes=(notes.strip() if notes else None),
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        row = self._repo.upsert_for_user(user_id=self.user_id, profile=profile)
        return InvestorProfile.from_row(row)


class WealthAdviserGoalService:
    def __init__(self, client, user_id: str) -> None:
        self.user_id = user_id
        self._repo = WealthAdviserGoalRepository(client)

    def list_active_goals(self, *, portfolio_id: Optional[str] = None) -> tuple[AdviserGoal, ...]:
        rows = self._repo.list_active_for_user(self.user_id, portfolio_id=portfolio_id)
        return tuple(AdviserGoal.from_row(row) for row in rows)

    def create_goal(
        self,
        *,
        portfolio_id: Optional[str],
        goal_type: str,
        title: str,
        target_date: Optional[str] = None,
        target_amount: Optional[float] = None,
        currency: Optional[str] = None,
        priority: int = 1,
        notes: Optional[str] = None,
    ) -> AdviserGoal:
        if goal_type.strip().upper() not in {item.value for item in GoalType}:
            raise ValueError("invalid_goal_type")
        row = self._repo.create(
            user_id=self.user_id,
            portfolio_id=portfolio_id,
            goal_type=goal_type,
            title=title,
            target_date=target_date,
            target_amount=target_amount,
            currency=currency,
            priority=priority,
            notes=notes,
        )
        return AdviserGoal.from_row(row)

    def archive_goal(self, goal_id: str) -> AdviserGoal:
        row = self._repo.archive(user_id=self.user_id, goal_id=goal_id)
        return AdviserGoal.from_row(row)

    def update_goal(self, goal_id: str, **updates) -> AdviserGoal:
        row = self._repo.update(user_id=self.user_id, goal_id=goal_id, updates=updates)
        return AdviserGoal.from_row(row)


PROFILE_ENUM_OPTIONS = {
    "investment_horizon": [item.value for item in InvestmentHorizon if item != InvestmentHorizon.UNKNOWN],
    "risk_preference": [item.value for item in RiskPreference if item != RiskPreference.UNKNOWN],
    "liquidity_need": [item.value for item in LiquidityNeed if item != LiquidityNeed.UNKNOWN],
    "cash_preference": [item.value for item in LiquidityNeed if item != LiquidityNeed.UNKNOWN],
    "concentration_preference": [
        item.value for item in ConcentrationPreference if item != ConcentrationPreference.UNKNOWN
    ],
    "income_need": [item.value for item in IncomeNeed if item != IncomeNeed.UNKNOWN],
    "experience_level": [item.value for item in ExperienceLevel if item != ExperienceLevel.UNKNOWN],
}

GOAL_TYPE_OPTIONS = [item.value for item in GoalType]
