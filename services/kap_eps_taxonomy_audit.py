"""Read-only audit of official KAP FY EPS taxonomy. Does not ingest EPS.

Existing SecurityFacts / KAP financial bridge do not map EPS. This module
only classifies whether official FY HTML exposes basic/diluted EPS.
It does not invent EPS from net income / shares and does not change P/E.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from services.kap_public_parser import parse_public_kap_html


CLASS_DIRECT_OFFICIAL_EPS = "DIRECT_OFFICIAL_EPS"
CLASS_DERIVABLE_UNDER_EXISTING_METHOD = "DERIVABLE_UNDER_EXISTING_METHOD"
CLASS_NOT_AVAILABLE = "NOT_AVAILABLE"
CLASS_METHODOLOGY_UNRESOLVED = "METHODOLOGY_UNRESOLVED"

BASIC_CONCEPTS = (
    "ifrs-full_BasicEarningsPerShare",
    "ifrs-full_BasicEarningsLossPerShare",
    "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
)
DILUTED_CONCEPTS = (
    "ifrs-full_DilutedEarningsPerShare",
    "ifrs-full_DilutedEarningsLossPerShare",
    "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations",
)
CONCEPT_HINTS = (
    "ifrs-full_BasicEarningsPerShare",
    "ifrs-full_DilutedEarningsPerShare",
    "ifrs-full_BasicEarningsLossPerShare",
    "ifrs-full_DilutedEarningsLossPerShare",
    "ifrs-full_EarningsPerShareAbstract",
)

_TYPED_VALUE_RE = re.compile(
    r"Pay Başına Kazanç(?: \(Zarar\))?.{0,400}?(\d[\d\.]{0,12},\d+)",
    re.S,
)


def _unescape_js(html: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"\\u([0-9a-fA-F]{4})", _repl, str(html or ""))


@dataclass(frozen=True)
class KapEpsTaxonomyAudit:
    symbol: str
    classification: str
    basic_exposed: bool
    diluted_exposed: bool
    existing_parser_valued_rows: int
    typed_dimension_values: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "classification": self.classification,
            "basic_exposed": self.basic_exposed,
            "diluted_exposed": self.diluted_exposed,
            "existing_parser_valued_rows": self.existing_parser_valued_rows,
            "typed_dimension_values": list(self.typed_dimension_values),
            "notes": list(self.notes),
        }


def _concepts_present(html: str) -> tuple[bool, bool]:
    blob = str(html or "")
    basic = any(token in blob for token in BASIC_CONCEPTS)
    diluted = any(token in blob for token in DILUTED_CONCEPTS)
    return basic, diluted


def audit_kap_eps_taxonomy(
    html: str,
    *,
    symbol: str,
    disclosure_id: str = "fixture",
) -> KapEpsTaxonomyAudit:
    """Classify official EPS exposure. Never returns inventable NI/shares EPS."""
    notes: list[str] = [
        "existing_kap_financial_bridge_does_not_map_eps",
        "pe_methodology_unchanged",
        "do_not_invent_eps_from_net_income_over_shares",
    ]
    basic, diluted = _concepts_present(html)
    valued = 0
    try:
        document = parse_public_kap_html(
            html,
            symbol=symbol,
            disclosure_id=disclosure_id,
            cached=True,
        )
        valued = sum(
            1
            for row in document.rows
            if any(token.casefold() in row.concept.casefold() for token in CONCEPT_HINTS)
            and any(value is not None for value in row.values)
        )
        observed = " ".join(document.observed_concepts)
        basic = basic or any(token in observed for token in BASIC_CONCEPTS)
        diluted = diluted or any(token in observed for token in DILUTED_CONCEPTS)
    except ValueError:
        notes.append("existing_public_parser_could_not_normalize_document")

    decoded = _unescape_js(html)
    typed_values = tuple(dict.fromkeys(_TYPED_VALUE_RE.findall(decoded)))
    if typed_values:
        notes.append("typed_dimension_eps_values_present_not_ingested")
    if valued:
        notes.append("existing_parser_extracted_eps_values")

    if valued:
        classification = CLASS_DIRECT_OFFICIAL_EPS
    elif typed_values and (basic or diluted):
        classification = CLASS_DIRECT_OFFICIAL_EPS
        notes.append("not_ingested_into_securityfacts")
    elif basic or diluted:
        classification = CLASS_NOT_AVAILABLE
        notes.append("taxonomy_headers_present_without_parseable_values")
    else:
        classification = CLASS_NOT_AVAILABLE

    return KapEpsTaxonomyAudit(
        symbol=str(symbol or "").upper(),
        classification=classification,
        basic_exposed=basic,
        diluted_exposed=diluted,
        existing_parser_valued_rows=valued,
        typed_dimension_values=typed_values,
        notes=tuple(notes),
    )


def existing_method_allows_invented_eps() -> bool:
    return False
