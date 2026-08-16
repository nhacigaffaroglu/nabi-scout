from __future__ import annotations

from config.universe_expansion_sources import dedupe_expansion_symbols
from repositories.universe_expansion_repository import UniverseExpansionRepository


def seed_universe_expansion_queue(
    repo: UniverseExpansionRepository,
    *,
    source_filter: set[str] | None = None,
) -> int:
    inserted = 0
    for symbol, source_universe, priority in dedupe_expansion_symbols():
        if source_filter and source_universe not in source_filter:
            continue
        existing = repo.get_by_symbol(symbol)
        if existing is not None:
            continue
        repo.upsert_pending(
            symbol,
            source_universe=source_universe,
            priority=priority,
        )
        inserted += 1
    return inserted
