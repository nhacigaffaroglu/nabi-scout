from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from services.universe_expansion_contract import PROVIDER_FMP, PROVIDER_SEC


@dataclass
class ProviderBudgetSnapshot:
    provider: str
    daily_budget: int
    interactive_reserve: int
    expansion_budget: int
    spent: int = 0
    reserved_interactive_remaining: int = 0
    expansion_remaining: int = 0

    def remaining(self) -> int:
        return max(0, self.daily_budget - self.spent)

    def expansion_can_spend(self, amount: int) -> bool:
        if amount <= 0:
            return True
        return self.spent + amount <= self.expansion_budget

    def record(self, amount: int) -> None:
        if amount > 0:
            self.spent += amount


@dataclass
class ProviderBudgetManager:
    config: UniverseExpansionBudgetConfig
    fmp: ProviderBudgetSnapshot = field(init=False)
    sec: ProviderBudgetSnapshot = field(init=False)
    _rate_limited: Dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.fmp = self._build_snapshot(
            PROVIDER_FMP,
            self.config.fmp_daily_call_budget,
            self.config.fmp_interactive_reserve_pct,
            self.config.fmp_expansion_reserve_pct,
        )
        self.sec = self._build_snapshot(
            PROVIDER_SEC,
            self.config.sec_daily_call_budget,
            0.0,
            self.config.sec_expansion_reserve_pct,
        )

    @staticmethod
    def _build_snapshot(
        provider: str,
        daily_budget: int,
        interactive_pct: float,
        expansion_pct: float,
    ) -> ProviderBudgetSnapshot:
        interactive_reserve = int(round(daily_budget * interactive_pct))
        expansion_budget = int(round(daily_budget * expansion_pct))
        return ProviderBudgetSnapshot(
            provider=provider,
            daily_budget=daily_budget,
            interactive_reserve=interactive_reserve,
            expansion_budget=expansion_budget,
            reserved_interactive_remaining=interactive_reserve,
            expansion_remaining=expansion_budget,
        )

    def _snapshot(self, provider: str) -> ProviderBudgetSnapshot:
        if provider == PROVIDER_FMP:
            return self.fmp
        if provider == PROVIDER_SEC:
            return self.sec
        raise KeyError(f"Unknown provider: {provider}")

    def is_rate_limited(self, provider: str) -> bool:
        return bool(self._rate_limited.get(provider))

    def mark_rate_limited(self, provider: str) -> None:
        self._rate_limited[provider] = True

    def can_spend(self, provider: str, operation: str, estimated_cost: int) -> bool:
        del operation
        if self.is_rate_limited(provider):
            return False
        snapshot = self._snapshot(provider)
        return snapshot.expansion_can_spend(estimated_cost)

    def record_spend(
        self,
        provider: str,
        operation: str,
        actual_cost: int,
    ) -> None:
        del operation
        if actual_cost <= 0:
            return
        snapshot = self._snapshot(provider)
        snapshot.record(actual_cost)
        snapshot.expansion_remaining = max(
            0,
            snapshot.expansion_budget - snapshot.spent,
        )
        snapshot.reserved_interactive_remaining = max(
            0,
            snapshot.daily_budget - snapshot.spent - snapshot.interactive_reserve,
        )

    def remaining(self, provider: str) -> int:
        return self._snapshot(provider).remaining()

    def expansion_remaining(self, provider: str) -> int:
        return self._snapshot(provider).expansion_remaining

    def interactive_reserve_remaining(self, provider: str) -> int:
        snapshot = self._snapshot(provider)
        return max(0, snapshot.daily_budget - snapshot.spent)

    def to_report(self) -> Dict[str, object]:
        return {
            "fmp_calls_used": self.fmp.spent,
            "sec_calls_used": self.sec.spent,
            "budget_remaining": {
                PROVIDER_FMP: self.fmp.remaining(),
                PROVIDER_SEC: self.sec.remaining(),
            },
            "expansion_remaining": {
                PROVIDER_FMP: self.fmp.expansion_remaining,
                PROVIDER_SEC: self.sec.expansion_remaining,
            },
            "interactive_reserve_remaining": {
                PROVIDER_FMP: max(
                    0,
                    self.fmp.daily_budget
                    - self.fmp.spent
                    - self.fmp.interactive_reserve,
                ),
            },
        }

    def can_afford_operations(self, costs: Mapping[str, int]) -> bool:
        for provider, cost in costs.items():
            if cost <= 0:
                continue
            if not self.can_spend(provider, "bundle", cost):
                return False
        return True
