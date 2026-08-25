"""Compact discovery/queue metrics for later monitoring. No dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)


@dataclass(frozen=True)
class UniverseDiscoveryMetrics:
    known_universe_size: int
    pending_participation: int
    retryable: int
    completed: int
    uygun: int
    uygun_degil: int
    kontrol_et: int

    def to_dict(self) -> dict[str, int]:
        return {
            "known_universe_size": self.known_universe_size,
            "pending_participation": self.pending_participation,
            "retryable": self.retryable,
            "completed": self.completed,
            "uygun": self.uygun,
            "uygun_degil": self.uygun_degil,
            "kontrol_et": self.kontrol_et,
        }


def collect_universe_discovery_metrics(
    repo: UniverseExpansionRepository,
    *,
    snapshots: Optional[Mapping[str, Mapping]] = None,
) -> UniverseDiscoveryMetrics:
    rows = repo.list_all()
    pending = 0
    retryable = 0
    completed = 0
    uygun = 0
    uygun_degil = 0
    kontrol_et = 0
    snapshot_status = {
        str(symbol or "").strip().upper(): str(
            row.get("status") or row.get("participation_status") or ""
        ).strip()
        for symbol, row in (snapshots or {}).items()
    }
    for row in rows:
        status = str(row.get("status") or "")
        if status == EXPANSION_STATUS_PENDING:
            pending += 1
        elif status == EXPANSION_STATUS_RETRYABLE:
            retryable += 1
        elif status == EXPANSION_STATUS_COMPLETED:
            completed += 1
        participation = str(row.get("participation_status") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        if not participation:
            participation = snapshot_status.get(symbol, "")
        if participation == PARTICIPATION_STATUS_UYGUN:
            uygun += 1
        elif participation == PARTICIPATION_STATUS_UYGUN_DEGIL:
            uygun_degil += 1
        elif participation == PARTICIPATION_STATUS_KONTROL_ET:
            kontrol_et += 1
    return UniverseDiscoveryMetrics(
        known_universe_size=len(rows),
        pending_participation=pending,
        retryable=retryable,
        completed=completed,
        uygun=uygun,
        uygun_degil=uygun_degil,
        kontrol_et=kontrol_et,
    )
