"""Qualify OpenFIGI mapping results. Identity is not instrument type.

Bond is never sukuk. Security names are never classification evidence.
Fund membership is never a tie-break.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from services.openfigi_client import (
    MATCH_ERROR,
    MATCH_EXACT_SINGLE,
    MATCH_MULTIPLE,
    MATCH_NONE,
    OpenFigiCandidate,
    OpenFigiJobResult,
)
from services.security_master_contract import (
    INSTRUMENT_CASH,
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_OTHER,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
    INSTRUMENT_UNKNOWN,
)
from services.sukuk_evidence_contract import EXPLICIT_SUKUK_TYPES

# Exact provider securityType / securityType2 tokens only. marketSector is inventory.
# Observed on SPSK 2026-08-28: EURO-DOLLAR, EURO MTN, Govt, Corp.
# PRIV PLACEMENT is not listed; it classifies only via securityType2 Corp/Govt.
# Bond / Govt / Corp remain debt, never sukuk. Do not infer from names.
OPENFIGI_FIXED_INCOME_EXACT = frozenset(
    {
        "BOND",
        "CORP",
        "GOVT",
        "GOVERNMENT",
        "GOVERNMENT BOND",
        "CORPORATE BOND",
        "TREASURY",
        "NOTE",
        "EURO-DOLLAR",
        "EURO MTN",
    }
)
OPENFIGI_EQUITY_EXACT = frozenset(
    {
        "COMMON STOCK",
        "PREF STOCK",
        "PREFERRED STOCK",
        "ORDINARY SHARES",
    }
)
OPENFIGI_ETF_EXACT = frozenset({"ETP", "ETF", "ETN"})
OPENFIGI_REIT_EXACT = frozenset({"REIT", "REIT EQUITY"})
OPENFIGI_CASH_EXACT = frozenset({"CASH", "MONEY MARKET"})

# These tokens are never sukuk even if the holding sits in SPSK.
NOT_SUKUK = frozenset(
    {
        "BOND",
        "CORP",
        "GOVT",
        "CORPORATE BOND",
        "GOVERNMENT BOND",
        "CERTIFICATE",
        "NOTE",
        "TRUST",
    }
)


@dataclass(frozen=True)
class OpenFigiQualification:
    match_status: str
    identity_resolved: bool
    instrument_type: str
    safety: str
    reason: str
    security_type: str
    security_type2: str
    market_sector: str
    figi: str
    provider_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_status": self.match_status,
            "identity_resolved": self.identity_resolved,
            "instrument_type": self.instrument_type,
            "safety": self.safety,
            "reason": self.reason,
            "securityType": self.security_type,
            "securityType2": self.security_type2,
            "marketSector": self.market_sector,
            "figi": self.figi,
            "provider_name": self.provider_name,
        }


def normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def normalize_type(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().replace("_", " ").split())


def is_explicit_openfigi_sukuk(*values: Any) -> bool:
    for value in values:
        text = normalize_type(value)
        if text in EXPLICIT_SUKUK_TYPES or text == "SUKUK":
            return True
    return False


def _classify_structured(security_type: str, security_type2: str) -> tuple[str, str, str]:
    types = (normalize_type(security_type), normalize_type(security_type2))
    if is_explicit_openfigi_sukuk(*types):
        return INSTRUMENT_SUKUK, "safe", "EXPLICIT_OPENFIGI_SUKUK"
    for token in types:
        if token in NOT_SUKUK and token in OPENFIGI_FIXED_INCOME_EXACT:
            return INSTRUMENT_FIXED_INCOME, "safe", f"OPENFIGI_FI:{token}"
        if token in OPENFIGI_FIXED_INCOME_EXACT:
            return INSTRUMENT_FIXED_INCOME, "safe", f"OPENFIGI_FI:{token}"
        if token in OPENFIGI_EQUITY_EXACT:
            return INSTRUMENT_EQUITY, "safe", f"OPENFIGI_EQUITY:{token}"
        if token in OPENFIGI_ETF_EXACT:
            return INSTRUMENT_ETF, "safe", f"OPENFIGI_ETF:{token}"
        if token in OPENFIGI_REIT_EXACT:
            return INSTRUMENT_REIT, "safe", f"OPENFIGI_REIT:{token}"
        if token in OPENFIGI_CASH_EXACT:
            return INSTRUMENT_CASH, "safe", f"OPENFIGI_CASH:{token}"
    if any(types):
        return INSTRUMENT_UNKNOWN, "unsafe", "UNREVIEWED_OPENFIGI_TYPE"
    return INSTRUMENT_UNKNOWN, "unsafe", "MISSING_OPENFIGI_TYPE"


def disambiguate_candidates(
    candidates: Sequence[OpenFigiCandidate],
    *,
    official_name: Any = None,
) -> tuple[str, Optional[OpenFigiCandidate]]:
    """Exact official-name match only. No fund tie-break. No first-result pick."""
    if not candidates:
        return MATCH_NONE, None
    figis = {row.figi for row in candidates if row.figi}
    if len(candidates) == 1 or len(figis) == 1:
        return MATCH_EXACT_SINGLE, candidates[0]
    target = normalize_name(official_name)
    if not target:
        return MATCH_MULTIPLE, None
    hits = [row for row in candidates if normalize_name(row.name) == target]
    if len(hits) == 1:
        return MATCH_EXACT_SINGLE, hits[0]
    return MATCH_MULTIPLE, None


def qualify_mapping(
    result: OpenFigiJobResult,
    *,
    official_name: Any = None,
) -> OpenFigiQualification:
    if result.match_status == MATCH_ERROR:
        return OpenFigiQualification(
            match_status=MATCH_ERROR,
            identity_resolved=False,
            instrument_type=INSTRUMENT_UNKNOWN,
            safety="unsafe",
            reason=result.error or "PROVIDER_ERROR",
            security_type="",
            security_type2="",
            market_sector="",
            figi="",
            provider_name="",
        )
    status, chosen = disambiguate_candidates(
        result.candidates, official_name=official_name
    )
    if result.match_status == MATCH_NONE or status == MATCH_NONE:
        return OpenFigiQualification(
            match_status=MATCH_NONE,
            identity_resolved=False,
            instrument_type=INSTRUMENT_UNKNOWN,
            safety="unsafe",
            reason=result.warning or "NO_MATCH",
            security_type="",
            security_type2="",
            market_sector="",
            figi="",
            provider_name="",
        )
    if status == MATCH_MULTIPLE or chosen is None:
        return OpenFigiQualification(
            match_status=MATCH_MULTIPLE,
            identity_resolved=False,
            instrument_type=INSTRUMENT_UNKNOWN,
            safety="unsafe",
            reason="MULTIPLE_MATCHES",
            security_type="",
            security_type2="",
            market_sector="",
            figi="",
            provider_name="",
        )
    instrument, safety, reason = _classify_structured(
        chosen.security_type, chosen.security_type2
    )
    return OpenFigiQualification(
        match_status=MATCH_EXACT_SINGLE,
        identity_resolved=True,
        instrument_type=instrument,
        safety=safety,
        reason=reason,
        security_type=chosen.security_type,
        security_type2=chosen.security_type2,
        market_sector=chosen.market_sector,
        figi=chosen.figi,
        provider_name=chosen.name,
    )
