"""Official KAP EPS unit semantics. Does not invent EPS from net income / shares.

US SecurityFacts.eps is diluted-first (US-GAAP) and IFRS-diluted then basic.
KAP filings use IFRS taxonomy, so BIST fy_eps follows that IFRS order.
Statement thousands scale is never applied to per-share amounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from services.kap_financial_contract import (
    IFRS_BASIC_AND_DILUTED_EPS,
    IFRS_BASIC_EPS,
    IFRS_BASIC_EPS_CONTINUING,
    IFRS_DILUTED_EPS,
    IFRS_DILUTED_EPS_CONTINUING,
)
from services.kap_public_contract import KapPublicTaxonomyRow


BASIS_ONE_TRY = "EARNINGS_PER_1_TRY_NOMINAL_QUOTE_UNIT"
BASIS_UNRESOLVED = "EPS_UNIT_UNRESOLVED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_CANONICAL = "CANONICAL"
STATUS_BLOCKED = "BLOCKED"

# Existing SEC IFRS tag order (sec_financial_client._IFRS_TAGS["eps"]).
IFRS_EPS_SELECTION_ORDER = (
    IFRS_DILUTED_EPS_CONTINUING,
    IFRS_DILUTED_EPS,
    IFRS_BASIC_AND_DILUTED_EPS,
    IFRS_BASIC_EPS_CONTINUING,
    IFRS_BASIC_EPS,
)

SELECTABLE_EPS_CONCEPTS = frozenset(IFRS_EPS_SELECTION_ORDER)
EXCLUDED_EPS_HINTS = (
    "DISCONTINUED",
    "ABSTRACT",
    "LINEITEMS",
)

_TAM_TL_RE = re.compile(r"\btam\s*tl\b", re.I)
_ONE_TRY_SHARE_RE = re.compile(
    r"nominal(?:\s*de[gğ]eri)?\s*1(?:[.,]00)?\s*(?:tl|try)\b",
    re.I,
)
_ONE_KR_RE = re.compile(
    r"nominal(?:\s*de[gğ]eri)?\s*1\s*kr",
    re.I,
)
_HUNDRED_SHARES_RE = re.compile(r"100\s*adet", re.I)
_KR_UNIT_RE = re.compile(r"\(kr\.?\)", re.I)


def _concept_key(concept: str) -> str:
    return str(concept or "").split("|", 1)[0].replace("_", "").replace("-", "").upper()


def is_eps_concept(concept: str) -> bool:
    key = _concept_key(concept)
    if not key or any(hint in key for hint in EXCLUDED_EPS_HINTS):
        return False
    return key in {_concept_key(item) for item in SELECTABLE_EPS_CONCEPTS}


def _parse_number(raw: object) -> Optional[Decimal]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.count(".") >= 2 and "," not in text:
        text = text.replace(".", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value.is_nan() or value.is_infinite():
        return None
    return value


@dataclass(frozen=True)
class KapEpsCandidate:
    taxonomy_concept: str
    typed_dimension: str
    reported_label: str
    reported_value: Optional[Decimal]
    currency_or_unit: str
    share_nominal_basis: Optional[str]
    share_count_basis: Optional[str]
    period_kind: str
    period_end: Optional[str]
    notification_id: str
    reporting_basis: str
    source: str
    current_period: bool
    classification: str
    canonical_value: Optional[Decimal]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "taxonomy_concept": self.taxonomy_concept,
            "typed_dimension": self.typed_dimension,
            "reported_label": self.reported_label,
            "reported_value": str(self.reported_value) if self.reported_value is not None else None,
            "currency_or_unit": self.currency_or_unit,
            "share_nominal_basis": self.share_nominal_basis,
            "share_count_basis": self.share_count_basis,
            "period_kind": self.period_kind,
            "period_end": self.period_end,
            "notification_id": self.notification_id,
            "reporting_basis": self.reporting_basis,
            "source": self.source,
            "current_period": self.current_period,
            "classification": self.classification,
            "canonical_value": str(self.canonical_value) if self.canonical_value is not None else None,
            "notes": list(self.notes),
        }


def classify_eps_basis(label: str) -> dict[str, object]:
    """Use official typed-dimension / caption text only. No NI/share inference."""
    text = str(label or "")
    notes: list[str] = []
    if _TAM_TL_RE.search(text) or _ONE_TRY_SHARE_RE.search(text):
        return {
            "classification": BASIS_ONE_TRY,
            "canonical_factor": Decimal("1"),
            "currency_or_unit": "TRY",
            "share_nominal_basis": "1.00 TRY",
            "share_count_basis": "1 share",
            "notes": ("explicit_full_try_or_1_try_nominal_share",),
        }
    if _ONE_KR_RE.search(text) and _HUNDRED_SHARES_RE.search(text):
        return {
            "classification": BASIS_ONE_TRY,
            "canonical_factor": Decimal("1"),
            "currency_or_unit": "TRY",
            "share_nominal_basis": "0.01 TRY",
            "share_count_basis": "100 shares",
            "notes": ("explicit_100_shares_of_1_kr_equals_1_try_nominal",),
        }
    if _ONE_KR_RE.search(text) and _KR_UNIT_RE.search(text):
        # kr per 1-kr share = TRY per 1 TRY quote unit (100 × 0.01 / 100 kr).
        notes.append("explicit_1_kr_share_in_kurus_equals_1_try_quote_unit_numerically")
        return {
            "classification": BASIS_ONE_TRY,
            "canonical_factor": Decimal("1"),
            "currency_or_unit": "KR",
            "share_nominal_basis": "0.01 TRY",
            "share_count_basis": "1 legal share",
            "notes": tuple(notes),
        }
    return {
        "classification": BASIS_UNRESOLVED,
        "canonical_factor": None,
        "currency_or_unit": "",
        "share_nominal_basis": None,
        "share_count_basis": None,
        "notes": ("no_explicit_share_nominal_or_quote_unit_on_eps_row",),
    }


def normalize_eps_value(reported: Optional[Decimal], factor: Optional[Decimal]) -> Optional[Decimal]:
    if reported is None or factor is None:
        return None
    try:
        return reported * factor
    except (InvalidOperation, TypeError):
        return None


def candidate_from_row(
    row: KapPublicTaxonomyRow,
    *,
    notification_id: str,
    source: str = "PUBLIC_KAP",
    reporting_basis: str = "",
) -> Optional[KapEpsCandidate]:
    if not is_eps_concept(row.concept):
        return None
    if not row.values or row.values[0] is None:
        return None
    reported = _parse_number(row.values[0])
    basis = classify_eps_basis(row.raw_label)
    factor = basis["canonical_factor"]
    canonical = normalize_eps_value(reported, factor if isinstance(factor, Decimal) else None)
    return KapEpsCandidate(
        taxonomy_concept=row.concept.split("|", 1)[0],
        typed_dimension=row.raw_label,
        reported_label=row.raw_label,
        reported_value=reported,
        currency_or_unit=str(basis["currency_or_unit"]),
        share_nominal_basis=basis["share_nominal_basis"] if isinstance(basis["share_nominal_basis"], str) else None,
        share_count_basis=basis["share_count_basis"] if isinstance(basis["share_count_basis"], str) else None,
        period_kind=row.period_kind,
        period_end=row.period_end,
        notification_id=notification_id,
        reporting_basis=reporting_basis,
        source=source,
        current_period=row.current_period,
        classification=str(basis["classification"]),
        canonical_value=canonical,
        notes=tuple(basis["notes"]),
    )


def select_canonical_eps(
    candidates: Iterable[KapEpsCandidate],
    *,
    require_fy: bool = True,
) -> Optional[KapEpsCandidate]:
    """IFRS diluted-then-basic. FY only. No discontinued. No invented values."""
    eligible: list[KapEpsCandidate] = []
    for item in candidates:
        if require_fy and item.period_kind != "FY":
            continue
        if not item.current_period:
            continue
        if item.classification != BASIS_ONE_TRY or item.canonical_value is None:
            continue
        if not is_eps_concept(item.taxonomy_concept):
            continue
        eligible.append(item)
    if not eligible:
        return None
    rank = {_concept_key(code): index for index, code in enumerate(IFRS_EPS_SELECTION_ORDER)}
    eligible.sort(key=lambda item: rank.get(_concept_key(item.taxonomy_concept), 99))
    return eligible[0]


def asels_anomaly_classification(raw: Optional[float]) -> str:
    """656.79 has no official unit; do not divide by 100."""
    del raw
    return BASIS_UNRESOLVED


def existing_method_allows_invented_eps() -> bool:
    return False
