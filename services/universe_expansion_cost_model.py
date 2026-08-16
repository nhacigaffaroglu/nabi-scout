from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

from services.universe_expansion_contract import PROVIDER_FMP, PROVIDER_SEC

# Logical remote-call estimates for bounded participation onboarding (cheap-first).
FMP_OPERATION_COSTS: Dict[str, int] = {
    "profile": 1,
    "historical_price_eod_light": 1,
    "quarterly_financials": 1,
    "ratios": 1,
    "metrics": 1,
    "news": 1,
    "peers": 1,
    "earnings": 1,
    "calendar": 1,
}

SEC_OPERATION_COSTS: Dict[str, int] = {
    "ticker_lookup": 1,
    "company_submissions": 1,
    "company_facts": 1,
    "inline_xbrl_filing": 1,
}

# Minimum bounded participation path (no CI).
PARTICIPATION_MINIMUM_OPERATIONS = (
    (PROVIDER_SEC, "company_facts"),
    (PROVIDER_FMP, "profile"),
    (PROVIDER_FMP, "historical_price_eod_light"),
)


@dataclass(frozen=True)
class OperationCostEstimate:
    by_provider: Dict[str, int]
    total: int
    operations: tuple[tuple[str, str], ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "by_provider": dict(self.by_provider),
            "total": self.total,
            "operations": list(self.operations),
        }


def estimate_participation_minimum_cost() -> OperationCostEstimate:
    by_provider: Dict[str, int] = {PROVIDER_FMP: 0, PROVIDER_SEC: 0}
    for provider, operation in PARTICIPATION_MINIMUM_OPERATIONS:
        cost = _operation_cost(provider, operation)
        by_provider[provider] = by_provider.get(provider, 0) + cost
    total = sum(by_provider.values())
    return OperationCostEstimate(
        by_provider=by_provider,
        total=total,
        operations=PARTICIPATION_MINIMUM_OPERATIONS,
    )


def _operation_cost(provider: str, operation: str) -> int:
    if provider == PROVIDER_FMP:
        return FMP_OPERATION_COSTS.get(operation, 1)
    if provider == PROVIDER_SEC:
        return SEC_OPERATION_COSTS.get(operation, 1)
    return 1


def estimate_from_provider_calls(
    provider_calls: Mapping[str, int],
) -> OperationCostEstimate:
    by_provider: Dict[str, int] = {PROVIDER_FMP: 0, PROVIDER_SEC: 0}
    operations: list[tuple[str, str]] = []
    for key, count in provider_calls.items():
        if not count:
            continue
        provider, _, operation = key.partition(":")
        if not operation:
            continue
        cost = _operation_cost(provider, operation) * int(count)
        by_provider[provider] = by_provider.get(provider, 0) + cost
        operations.append((provider, operation))
    return OperationCostEstimate(
        by_provider=by_provider,
        total=sum(by_provider.values()),
        operations=tuple(operations),
    )
