"""Security Master v1 fact vocabulary.

Facts answer: what type is identifier X according to source Y?
Policy mapping stays in portfolio_economic_exposure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

IDENTIFIER_TYPE_TICKER = "TICKER"
IDENTIFIER_TYPE_CUSIP = "CUSIP"
IDENTIFIER_TYPE_SEDOL = "SEDOL"
IDENTIFIER_TYPE_ISIN = "ISIN"

IDENTIFIER_TYPES = (
    IDENTIFIER_TYPE_TICKER,
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_ISIN,
)

INSTRUMENT_EQUITY = "EQUITY"
INSTRUMENT_REIT = "REIT"
INSTRUMENT_SUKUK = "SUKUK"
INSTRUMENT_FIXED_INCOME = "FIXED_INCOME"
INSTRUMENT_CASH = "CASH"
INSTRUMENT_ETF = "ETF"
INSTRUMENT_COMMODITY = "COMMODITY"
INSTRUMENT_OTHER = "OTHER"
INSTRUMENT_UNKNOWN = "UNKNOWN"

INSTRUMENT_TYPES = (
    INSTRUMENT_EQUITY,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_CASH,
    INSTRUMENT_ETF,
    INSTRUMENT_COMMODITY,
    INSTRUMENT_OTHER,
    INSTRUMENT_UNKNOWN,
)

SOURCE_US_LISTING = "us_listing"
SOURCE_PROVIDER_EXPLICIT = "provider_explicit"
SOURCE_CANONICAL_STATIC = "canonical_static"

# Lower rank wins. Equal rank with disagreeing types is CONFLICT, not newest-row.
SOURCE_PRECEDENCE = {
    SOURCE_US_LISTING: 10,
    SOURCE_PROVIDER_EXPLICIT: 20,
    SOURCE_CANONICAL_STATIC: 30,
}

RESOLUTION_RESOLVED = "RESOLVED"
RESOLUTION_UNKNOWN = "UNKNOWN"
RESOLUTION_CONFLICT = "CONFLICT"

# Security Master instrument_type → existing holding.asset_type policy keys.
# Unmapped types stay unresolved so _HOLDING_ASSET_TYPE_MAP is not duplicated.
INSTRUMENT_TO_POLICY_ASSET_TYPE = {
    INSTRUMENT_EQUITY: "equity",
    INSTRUMENT_REIT: "reit",
    INSTRUMENT_SUKUK: "sukuk",
    INSTRUMENT_FIXED_INCOME: "fixed_income",
    INSTRUMENT_CASH: "cash",
    INSTRUMENT_COMMODITY: "commodity",
}


@dataclass(frozen=True)
class SecurityFact:
    identifier: str
    identifier_type: str
    instrument_type: str
    source: str
    observed_at: str
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    issuer_name: Optional[str] = None
    source_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "instrument_type": self.instrument_type,
            "source": self.source,
            "observed_at": self.observed_at,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "issuer_name": self.issuer_name,
            "source_reference": self.source_reference,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class SecurityResolution:
    identifier: str
    identifier_type: str
    instrument_type: str
    status: str
    source: Optional[str]
    observed_at: Optional[str]
    facts: tuple[SecurityFact, ...] = ()
    limitation: str = ""

    @property
    def policy_asset_type(self) -> Optional[str]:
        if self.status != RESOLUTION_RESOLVED:
            return None
        return INSTRUMENT_TO_POLICY_ASSET_TYPE.get(self.instrument_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "instrument_type": self.instrument_type,
            "status": self.status,
            "source": self.source,
            "observed_at": self.observed_at,
            "limitation": self.limitation,
            "facts": [row.to_dict() for row in self.facts],
        }
