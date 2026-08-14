from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class InvestmentHorizon(str, Enum):
    UNKNOWN = "UNKNOWN"
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"
    VERY_LONG = "VERY_LONG"


class RiskPreference(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class LiquidityNeed(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ConcentrationPreference(str, Enum):
    UNKNOWN = "UNKNOWN"
    AVOID = "AVOID"
    MODERATE = "MODERATE"
    ACCEPT_HIGH = "ACCEPT_HIGH"


class ExperienceLevel(str, Enum):
    UNKNOWN = "UNKNOWN"
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class IncomeNeed(str, Enum):
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class GoalType(str, Enum):
    LONG_TERM_GROWTH = "LONG_TERM_GROWTH"
    CAPITAL_PRESERVATION = "CAPITAL_PRESERVATION"
    INCOME = "INCOME"
    LIQUIDITY = "LIQUIDITY"
    MAJOR_PURCHASE = "MAJOR_PURCHASE"
    RETIREMENT = "RETIREMENT"
    EDUCATION = "EDUCATION"
    EMERGENCY_RESERVE = "EMERGENCY_RESERVE"
    CUSTOM = "CUSTOM"


PROFILE_FIELD_NAMES = (
    "investment_horizon",
    "risk_preference",
    "liquidity_need",
    "cash_preference",
    "concentration_preference",
    "income_need",
    "experience_level",
)


def _optional_enum(value: Optional[str], enum_cls: type[Enum]) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip().upper()
    if normalized == "UNKNOWN":
        return None
    if normalized not in {item.value for item in enum_cls}:
        return None
    return normalized


@dataclass(frozen=True)
class InvestorProfile:
    user_id: str
    profile_version: int
    investment_horizon: Optional[str]
    risk_preference: Optional[str]
    liquidity_need: Optional[str]
    cash_preference: Optional[str]
    concentration_preference: Optional[str]
    income_need: Optional[str]
    experience_level: Optional[str]
    notes: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def empty(cls, user_id: str) -> "InvestorProfile":
        return cls(
            user_id=user_id,
            profile_version=1,
            investment_horizon=None,
            risk_preference=None,
            liquidity_need=None,
            cash_preference=None,
            concentration_preference=None,
            income_need=None,
            experience_level=None,
            notes=None,
            created_at=None,
            updated_at=None,
        )

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "InvestorProfile":
        return cls(
            user_id=str(row["user_id"]),
            profile_version=int(row.get("profile_version") or 1),
            investment_horizon=_optional_enum(row.get("investment_horizon"), InvestmentHorizon),
            risk_preference=_optional_enum(row.get("risk_preference"), RiskPreference),
            liquidity_need=_optional_enum(row.get("liquidity_need"), LiquidityNeed),
            cash_preference=_optional_enum(row.get("cash_preference"), LiquidityNeed),
            concentration_preference=_optional_enum(
                row.get("concentration_preference"), ConcentrationPreference
            ),
            income_need=_optional_enum(row.get("income_need"), IncomeNeed),
            experience_level=_optional_enum(row.get("experience_level"), ExperienceLevel),
            notes=(str(row["notes"]).strip() if row.get("notes") else None),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def missing_fields(self) -> Tuple[str, ...]:
        values = {
            "investment_horizon": self.investment_horizon,
            "risk_preference": self.risk_preference,
            "liquidity_need": self.liquidity_need,
            "cash_preference": self.cash_preference,
            "concentration_preference": self.concentration_preference,
            "income_need": self.income_need,
            "experience_level": self.experience_level,
        }
        return tuple(field for field, value in values.items() if not value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "profile_version": self.profile_version,
            "investment_horizon": self.investment_horizon,
            "risk_preference": self.risk_preference,
            "liquidity_need": self.liquidity_need,
            "cash_preference": self.cash_preference,
            "concentration_preference": self.concentration_preference,
            "income_need": self.income_need,
            "experience_level": self.experience_level,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "missing_fields": list(self.missing_fields()),
        }


@dataclass(frozen=True)
class AdviserGoal:
    id: str
    user_id: str
    portfolio_id: Optional[str]
    goal_type: str
    title: str
    target_date: Optional[str]
    target_amount: Optional[float]
    currency: Optional[str]
    priority: int
    notes: Optional[str]
    active: bool
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "AdviserGoal":
        target_amount = row.get("target_amount")
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
            goal_type=str(row["goal_type"]).strip().upper(),
            title=str(row["title"]).strip(),
            target_date=row.get("target_date"),
            target_amount=float(target_amount) if target_amount is not None else None,
            currency=(str(row["currency"]).strip().upper() if row.get("currency") else None),
            priority=int(row.get("priority") or 1),
            notes=(str(row["notes"]).strip() if row.get("notes") else None),
            active=bool(row.get("active", True)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "portfolio_id": self.portfolio_id,
            "goal_type": self.goal_type,
            "title": self.title,
            "target_date": self.target_date,
            "target_amount": self.target_amount,
            "currency": self.currency,
            "priority": self.priority,
            "notes": self.notes,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
