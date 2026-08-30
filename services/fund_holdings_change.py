"""Snapshot identity and incremental holdings change detection.

Identity is (fund, as_of, holding identifier). No production writes.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Optional, Sequence

from services.fund_product_contract import HoldingsChangeSet
from services.official_fund_holdings_client import OfficialHolding, OfficialHoldingsFile
from services.official_fund_holdings_ingest import holdings_fingerprint


def holding_snapshot_identity(
    *,
    fund_symbol: str,
    as_of: date | str,
    holding_identifier: str,
) -> tuple[str, str, str]:
    as_of_text = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    return (
        str(fund_symbol or "").strip().upper(),
        as_of_text,
        str(holding_identifier or "").strip().upper(),
    )


def _weight_map(rows: Sequence[OfficialHolding]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        key = str(row.holding_identifier or "").strip().upper()
        if not key:
            continue
        out[key] = float(row.weight_pct)
    return out


def detect_holdings_changes(
    previous: Optional[OfficialHoldingsFile],
    current: OfficialHoldingsFile,
    *,
    weight_epsilon: float = 0.01,
) -> HoldingsChangeSet:
    current_map = _weight_map(current.holdings)
    if previous is None:
        return HoldingsChangeSet(
            fund_symbol=current.fund_symbol,
            previous_as_of=None,
            current_as_of=current.as_of.isoformat(),
            new_holdings_date=True,
            added=tuple(sorted(current_map)),
            removed=(),
            weight_changed=(),
        )
    previous_map = _weight_map(previous.holdings)
    added = tuple(sorted(key for key in current_map if key not in previous_map))
    removed = tuple(sorted(key for key in previous_map if key not in current_map))
    changed = tuple(
        sorted(
            key
            for key in current_map
            if key in previous_map and abs(current_map[key] - previous_map[key]) > weight_epsilon
        )
    )
    return HoldingsChangeSet(
        fund_symbol=current.fund_symbol,
        previous_as_of=previous.as_of.isoformat(),
        current_as_of=current.as_of.isoformat(),
        new_holdings_date=previous.as_of != current.as_of,
        added=added,
        removed=removed,
        weight_changed=changed,
    )


def same_holdings_content(
    previous: Sequence[Mapping[str, object]] | OfficialHoldingsFile,
    current: Sequence[Mapping[str, object]] | OfficialHoldingsFile,
) -> bool:
    left = previous.holdings if isinstance(previous, OfficialHoldingsFile) else previous
    right = current.holdings if isinstance(current, OfficialHoldingsFile) else current
    return holdings_fingerprint(left) == holdings_fingerprint(right)
