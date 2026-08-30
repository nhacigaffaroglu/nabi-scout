"""Official Borsa Istanbul BIST Katılım Tüm membership vocabulary.

Read-only public evidence. Does not emit Participation verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


BORSA_ISTANBUL_KATILIM_PAGE = "https://www.borsaistanbul.com/katilim-finans"
BORSA_ISTANBUL_KATILIM_CSV_PATH = "/datum/hisse_endeks_katilim_ds.csv"
BORSA_ISTANBUL_HOST = "https://www.borsaistanbul.com"

INDEX_BIST_KATILIM_TUM = "XKTUM"
UNIVERSE_BIST_KATILIM_TUM = "BIST_KATILIM_TUM"
SOURCE_BORSA_ISTANBUL = "BORSA_ISTANBUL"

MEMBERSHIP_MEMBER = "MEMBER"
MEMBERSHIP_NOT_LISTED = "NOT_LISTED"
MEMBERSHIP_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
MEMBERSHIP_UNKNOWN = "UNKNOWN"

LIMITATION_NETWORK = "BORSA_KATILIM_NETWORK_FAILURE"
LIMITATION_HTTP = "BORSA_KATILIM_HTTP_ERROR"
LIMITATION_STRUCTURE = "BORSA_KATILIM_UNEXPECTED_STRUCTURE"
LIMITATION_TRANSIENT = "BORSA_KATILIM_TRANSIENT_FAILURE_NOT_NEGATIVE"


def borsa_katilim_csv_url() -> str:
    return f"{BORSA_ISTANBUL_HOST}{BORSA_ISTANBUL_KATILIM_CSV_PATH}"


@dataclass(frozen=True)
class BistKatilimMember:
    symbol: str
    series_code: str
    constituent_name: str
    membership: bool
    index_code: str
    index_name: str
    universe: str
    source: str
    source_url: str
    as_of: Optional[str] = None
    observed_at: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "series_code": self.series_code,
            "constituent_name": self.constituent_name,
            "membership": self.membership,
            "index_code": self.index_code,
            "index_name": self.index_name,
            "universe": self.universe,
            "source": self.source,
            "source_url": self.source_url,
            "as_of": self.as_of,
            "observed_at": self.observed_at,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class BistKatilimTumSnapshot:
    members: tuple[BistKatilimMember, ...]
    source: str
    source_url: str
    as_of: Optional[str]
    observed_at: str
    retrieved: bool
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_count": len(self.members),
            "source": self.source,
            "source_url": self.source_url,
            "as_of": self.as_of,
            "observed_at": self.observed_at,
            "retrieved": self.retrieved,
            "limitation": self.limitation,
        }


@dataclass(frozen=True)
class BistKatilimMembership:
    symbol: str
    status: str
    membership: Optional[bool]
    member: Optional[BistKatilimMember]
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "membership": self.membership,
            "member": self.member.to_dict() if self.member else None,
            "limitation": self.limitation,
        }


class BistKatilimTumSourceError(RuntimeError):
    pass
