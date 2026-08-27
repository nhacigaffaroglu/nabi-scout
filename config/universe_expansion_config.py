from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return default


@dataclass(frozen=True)
class UniverseExpansionBudgetConfig:
    fmp_daily_call_budget: int = 250
    sec_daily_call_budget: int = 500
    fmp_interactive_reserve_pct: float = 0.35
    fmp_expansion_reserve_pct: float = 0.50
    sec_expansion_reserve_pct: float = 0.60
    stale_in_progress_minutes: int = 120
    default_retry_backoff_hours: int = 6
    plan_restricted_retry_days: int = 7
    max_errors_before_stop: int = 5
    max_symbols_per_run: int = 30
    # How many identities may be known/queued. Independent of per-run processing.
    discovery_capacity: int = 8000
    # How many NEW identities a single discovery ingest may insert.
    max_new_symbols_per_ingest: int = 30

    @classmethod
    def from_env(cls) -> "UniverseExpansionBudgetConfig":
        max_symbols = _env_int("UNIVERSE_EXPANSION_MAX_SYMBOLS_PER_RUN", 30)
        return cls(
            fmp_daily_call_budget=_env_int("FMP_DAILY_CALL_BUDGET", 250),
            sec_daily_call_budget=_env_int("SEC_DAILY_CALL_BUDGET", 500),
            fmp_interactive_reserve_pct=_env_float("FMP_INTERACTIVE_RESERVE_PCT", 0.35),
            fmp_expansion_reserve_pct=_env_float("FMP_EXPANSION_RESERVE_PCT", 0.50),
            sec_expansion_reserve_pct=_env_float("SEC_EXPANSION_RESERVE_PCT", 0.60),
            stale_in_progress_minutes=_env_int("UNIVERSE_EXPANSION_STALE_MINUTES", 120),
            default_retry_backoff_hours=_env_int("UNIVERSE_EXPANSION_RETRY_HOURS", 6),
            plan_restricted_retry_days=_env_int("UNIVERSE_EXPANSION_PLAN_RETRY_DAYS", 7),
            max_errors_before_stop=_env_int("UNIVERSE_EXPANSION_MAX_ERRORS", 5),
            max_symbols_per_run=max_symbols,
            discovery_capacity=_env_int("UNIVERSE_DISCOVERY_CAPACITY", 8000),
            max_new_symbols_per_ingest=_env_int(
                "UNIVERSE_DISCOVERY_MAX_NEW_SYMBOLS_PER_INGEST",
                30,
            ),
        )
