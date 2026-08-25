"""Minimal external-signal hook into discovery. No X/automation integration."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.universe_discovery_service import (
    DiscoveryIngestReport,
    propose_external_discovery_symbols,
)
from services.universe_listing_identity import EXTERNAL_SIGNAL_SOURCE


def propose_symbols_from_external_signal(
    symbols: Sequence[Any],
    *,
    repo: UniverseExpansionRepository,
    discovery_capacity: Optional[int] = None,
    source: str = EXTERNAL_SIGNAL_SOURCE,
    names: Optional[Mapping[str, str]] = None,
) -> DiscoveryIngestReport:
    """external signal → proposed symbol → dedupe → discovery/participation queue.

    Must never mark Uygun, trigger Scanner, or create ADAY / GÜÇLÜ ADAY.
    """
    return propose_external_discovery_symbols(
        symbols,
        repo=repo,
        discovery_capacity=discovery_capacity,
        source=source,
        names=names,
    )
