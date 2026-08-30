"""Identifier aliases and economic classification. Not instrument type.

instrument_type stays on Security Master. Economic layer is a separate fact.
A security may have many identifiers; they resolve to one canonical_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.security_master_contract import (
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_ISIN,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
)

IDENTIFIER_TYPE_FIGI = "FIGI"
IDENTITY_IDENTIFIER_TYPES = (
    IDENTIFIER_TYPE_TICKER,
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_ISIN,
    IDENTIFIER_TYPE_FIGI,
)

SOURCE_REGULATOR_EXPLICIT = "regulator_explicit"
SOURCE_PROVIDER_EXPLICIT = "provider_explicit"
SOURCE_CANONICAL_STATIC = "canonical_static"
SOURCE_IDENTIFIER_ALIAS = "identifier_alias"
SOURCE_ECONOMIC_CLASSIFICATION = "economic_classification"

IDENTITY_FACT_SOURCES = frozenset(
    {SOURCE_IDENTIFIER_ALIAS, SOURCE_ECONOMIC_CLASSIFICATION}
)

# Separate from instrument SOURCE_PRECEDENCE. Lower rank wins.
ECONOMIC_SOURCE_PRECEDENCE = {
    SOURCE_REGULATOR_EXPLICIT: 10,
    SOURCE_PROVIDER_EXPLICIT: 20,
    SOURCE_CANONICAL_STATIC: 30,
}

ECONOMIC_LAYERS = (
    "equity",
    "fixed_income",
    "sukuk",
    "real_estate",
    "cash",
    "cash_like",
    "commodity",
    "other",
)

EVIDENCE_OPENFIGI_SECURITY_TYPE = "openfigi.securityType"
EVIDENCE_OPENFIGI_MAPPING = "openfigi.v3.mapping"


def canonical_id_from_figi(figi: Any) -> str:
    text = str(figi or "").strip().upper()
    return f"FIGI:{text}" if text else ""


@dataclass(frozen=True)
class IdentifierAlias:
    identifier: str
    identifier_type: str
    canonical_id: str
    source: str
    observed_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "canonical_id": self.canonical_id,
            "source": self.source,
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class EconomicClassification:
    canonical_id: str
    economic_layer: str
    source: str
    evidence_type: str
    evidence_reference: str
    status: str
    observed_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "economic_layer": self.economic_layer,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "evidence_reference": self.evidence_reference,
            "status": self.status,
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class EconomicResolution:
    canonical_id: Optional[str]
    economic_layer: Optional[str]
    status: str
    source: Optional[str] = None
    limitation: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == RESOLUTION_RESOLVED and bool(self.economic_layer)
