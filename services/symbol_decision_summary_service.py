from __future__ import annotations

from typing import Iterable, Mapping, Optional, Tuple

from services.decision_outcome_contract import DecisionOutcome
from services.decision_outcome_engine import build_decision_outcome
from services.decision_learning_engine import build_decision_learning_insights


def build_symbol_decision_summary(
    *,
    symbol: str,
    journal_entries: Iterable[Mapping[str, object]],
    outcomes: Iterable[DecisionOutcome],
) -> dict:
    sym = symbol.strip().upper()
    entries = [row for row in journal_entries if str(row.get("symbol") or "").upper() == sym]
    outcome_rows = [row for row in outcomes if row.symbol == sym]
    insights = build_decision_learning_insights(
        outcomes=outcome_rows,
        journal_entries=entries,
    )
    latest = entries[0] if entries else None
    latest_outcome = outcome_rows[0] if outcome_rows else None
    return {
        "decision_count": len(entries),
        "latest_rationale": (latest or {}).get("thesis"),
        "latest_action": (latest or {}).get("action_context"),
        "outcome_status": latest_outcome.outcome_status if latest_outcome else None,
        "outcome_pct": latest_outcome.percentage_outcome if latest_outcome else None,
        "learning_flags": [insight.insight_type for insight in insights],
    }
