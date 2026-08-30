"""Parse the official public Borsa Katılım constituents CSV."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from services.bist_katilim_tum_contract import (
    INDEX_BIST_KATILIM_TUM,
    LIMITATION_STRUCTURE,
    MEMBERSHIP_MEMBER,
    MEMBERSHIP_NOT_LISTED,
    MEMBERSHIP_SOURCE_UNAVAILABLE,
    MEMBERSHIP_UNKNOWN,
    SOURCE_BORSA_ISTANBUL,
    UNIVERSE_BIST_KATILIM_TUM,
    BistKatilimMember,
    BistKatilimMembership,
    BistKatilimTumSnapshot,
    BistKatilimTumSourceError,
    borsa_katilim_csv_url,
)


def canonicalize_bist_series_code(raw: object) -> str:
    """ASELS.E → ASELS. Official Borsa equity series suffix only. Symbol-generic."""
    text = str(raw or "").strip().upper()
    if text.endswith(".E"):
        base = text[:-2]
        if base.isalnum():
            return base
    return text


def _as_of_iso(raw: str) -> Optional[str]:
    text = str(raw or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_bist_katilim_csv(
    csv_text: str,
    *,
    source_url: str = "",
    observed_at: str = "",
) -> BistKatilimTumSnapshot:
    lines = [line.strip() for line in str(csv_text or "").replace("\r\n", "\n").split("\n") if line.strip()]
    if len(lines) < 3:
        raise BistKatilimTumSourceError(LIMITATION_STRUCTURE)
    header = lines[0].upper()
    if "BILESEN KODU" not in header and "CONSTITUENT CODE" not in header:
        raise BistKatilimTumSourceError(LIMITATION_STRUCTURE)

    data_start = 1
    if "CONSTITUENT CODE" in lines[1].upper():
        data_start = 2

    members: list[BistKatilimMember] = []
    as_of = None
    observed = observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = source_url or borsa_katilim_csv_url()

    for line in lines[data_start:]:
        parts = line.split(";")
        if len(parts) < 6:
            continue
        series = parts[0].strip().upper()
        index_code = parts[2].strip().upper()
        if index_code != INDEX_BIST_KATILIM_TUM:
            continue
        symbol = canonicalize_bist_series_code(series)
        if not symbol:
            continue
        row_as_of = _as_of_iso(parts[5])
        if as_of is None:
            as_of = row_as_of
        members.append(
            BistKatilimMember(
                symbol=symbol,
                series_code=series,
                constituent_name=parts[1].strip(),
                membership=True,
                index_code=INDEX_BIST_KATILIM_TUM,
                index_name=parts[3].strip(),
                universe=UNIVERSE_BIST_KATILIM_TUM,
                source=SOURCE_BORSA_ISTANBUL,
                source_url=url,
                as_of=row_as_of,
                observed_at=observed,
                provenance={
                    "index_code": INDEX_BIST_KATILIM_TUM,
                    "series_code": series,
                    "row": line,
                },
            )
        )

    if not members:
        raise BistKatilimTumSourceError(LIMITATION_STRUCTURE)

    unique: dict[str, BistKatilimMember] = {}
    for member in members:
        unique[member.symbol] = member

    return BistKatilimTumSnapshot(
        members=tuple(sorted(unique.values(), key=lambda item: item.symbol)),
        source=SOURCE_BORSA_ISTANBUL,
        source_url=url,
        as_of=as_of,
        observed_at=observed,
        retrieved=True,
    )


def membership_for_symbol(
    snapshot: Optional[BistKatilimTumSnapshot],
    symbol: str,
    *,
    source_unavailable: bool = False,
) -> BistKatilimMembership:
    canon = canonicalize_bist_series_code(symbol)
    if source_unavailable or snapshot is None or not snapshot.retrieved:
        return BistKatilimMembership(
            symbol=canon,
            status=MEMBERSHIP_SOURCE_UNAVAILABLE,
            membership=None,
            member=None,
            limitation="Absence is not a negative verdict.",
        )
    for member in snapshot.members:
        if member.symbol == canon:
            return BistKatilimMembership(
                symbol=canon,
                status=MEMBERSHIP_MEMBER,
                membership=True,
                member=member,
            )
    if not canon:
        return BistKatilimMembership(
            symbol=canon,
            status=MEMBERSHIP_UNKNOWN,
            membership=None,
            member=None,
        )
    return BistKatilimMembership(
        symbol=canon,
        status=MEMBERSHIP_NOT_LISTED,
        membership=False,
        member=None,
        limitation="NOT_LISTED is not UYGUN_DEGIL.",
    )
