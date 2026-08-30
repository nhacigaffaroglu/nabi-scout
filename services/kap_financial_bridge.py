"""Bridge normalized KAP facts into SecurityFacts and Participation inputs.

Does not produce Participation verdicts or lift SI/8E. Identity must be
bist_listing. KAP facts never attach to US symbols.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from services.kap_financial_contract import KapNormalizedBundle, KapRawFinancialLine
from services.kap_financial_normalization import (
    fy_facts_only,
    normalize_kap_lines,
)
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_provenance import SOURCE_KAP, FinancialFieldProvenance
from services.security_master_contract import RESOLUTION_RESOLVED, SOURCE_BIST
from services.security_master_service import SecurityMasterService


MISSING_REQUIRED_FACT = "MISSING_REQUIRED_FACT"

PARTICIPATION_SUPPORTED_FROM_KAP = (
    "total_revenue",
    "total_assets",
    "total_debt",
    "cash",
)

# Existing methodology fields that KAP financial statements do not safely fill.
PARTICIPATION_MISSING_REQUIRED = (
    "cash_and_interest_bearing_securities",
    "accounts_receivable",
    "non_permissible_revenue",
    "interest_bearing_debt",
    "market_capitalization",
    "average_market_cap_24m",
)


class KapIdentityError(ValueError):
    """KAP facts require a resolved bist_listing identity."""


def resolve_bist_financial_identity(
    symbol: str,
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> Any:
    master = security_master or SecurityMasterService()
    resolution = master.resolve_security(symbol)
    if resolution.status != RESOLUTION_RESOLVED or resolution.source != SOURCE_BIST:
        raise KapIdentityError(
            f"{symbol} is not a resolved bist_listing identity; KAP facts are refused."
        )
    return resolution


def build_kap_normalized_bundle(
    symbol: str,
    lines: Iterable[KapRawFinancialLine],
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> KapNormalizedBundle:
    resolution = resolve_bist_financial_identity(symbol, security_master=security_master)
    return normalize_kap_lines(
        lines,
        symbol=resolution.identifier,
        identity_source=SOURCE_BIST,
    )


def kap_security_facts_payload(bundle: KapNormalizedBundle) -> dict[str, Any]:
    """FY-only payload for SecurityFacts. YTD/Q stay on the KAP bundle."""
    payload: dict[str, Any] = {
        "symbol": bundle.symbol,
        "currency": "",
        "financial_period_end": None,
        "period_kind": "FY",
        "source": "kap_normalized",
    }
    for fact in fy_facts_only(bundle.mapped):
        payload[fact.field] = fact.normalized_value
        payload["currency"] = payload["currency"] or fact.currency
        payload["financial_period_end"] = payload["financial_period_end"] or fact.period_end
    for derived in bundle.derived:
        if derived.value is None or derived.period_compatibility != "FY":
            continue
        if derived.field not in payload:
            payload[derived.field] = derived.value
    return payload


def _as_of_date(raw: Optional[str]) -> Optional[date]:
    text = str(raw or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def participation_inputs_from_kap(
    bundle: KapNormalizedBundle,
) -> tuple[ParticipationFinancialInputs, tuple[str, ...]]:
    """Map supported KAP FY facts. Does not evaluate a Participation screen."""
    fy = {item.field: item for item in fy_facts_only(bundle.mapped)}
    missing = list(PARTICIPATION_MISSING_REQUIRED)
    as_of = next((item.period_end for item in fy.values() if item.period_end), None)
    provenance: list[tuple[str, FinancialFieldProvenance]] = []

    def _value(kap_field: str, input_field: str) -> Optional[float]:
        fact = fy.get(kap_field)
        if fact is None:
            return None
        provenance.append(
            (
                input_field,
                FinancialFieldProvenance(
                    source=SOURCE_KAP,
                    source_fields=(fact.account_code or fact.field,),
                    period=fact.period_kind,
                ),
            )
        )
        return fact.normalized_value

    inputs = ParticipationFinancialInputs(
        symbol=bundle.symbol,
        as_of_date=_as_of_date(as_of),
        total_revenue=_value("revenue", "total_revenue"),
        total_assets=_value("total_assets", "total_assets"),
        total_debt=_value("total_debt", "total_debt"),
        cash=_value("cash", "cash"),
        source_evidence=(("source", SOURCE_KAP), ("identity", bundle.identity_source)),
        field_provenance=tuple(provenance),
    )
    return inputs, tuple(f"{MISSING_REQUIRED_FACT}:{name}" for name in missing)


def is_us_symbol_blocked_from_kap(symbol: str) -> bool:
    from services.bist_symbol_mapping import normalize_bist_symbol

    return normalize_bist_symbol(symbol) is None
