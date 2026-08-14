from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from services.participation_business_contract import (
    BusinessActivityEvidence,
    BusinessRevenueEvidence,
)
from services.participation_business_rules_registry import (
    SharedKeywordPolicy,
    StructuredSectorLabels,
    get_methodology_business_rules,
    load_business_rules_registry,
    resolve_sic_mapping,
)

COVERAGE_PROHIBITED_FOUND = "PROHIBITED_EVIDENCE_FOUND"
COVERAGE_NO_PROHIBITED_SUFFICIENT = "NO_PROHIBITED_ACTIVITY_FOUND_WITH_SUFFICIENT_COVERAGE"
COVERAGE_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

_TRUSTED_SOURCE_MARKERS = ("sec", "fmp", "candidate_record")
_MIN_DESCRIPTION_CHARS = 40


@dataclass(frozen=True)
class BusinessActivityCoverageResult:
    state: str
    limitations: Tuple[str, ...] = ()
    sources: Tuple[str, ...] = ()


def _trusted_source(source: Optional[str]) -> bool:
    lowered = str(source or "").lower()
    return any(marker in lowered for marker in _TRUSTED_SOURCE_MARKERS)


def _normalize_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _structured_label_match(
    label: Optional[str],
    structured_labels: StructuredSectorLabels,
    prohibited_categories: Sequence[str],
) -> Tuple[Optional[str], Optional[str]]:
    normalized = _normalize_label(label)
    if normalized is None:
        return None, None
    for category in prohibited_categories:
        if normalized in structured_labels.definitive.get(category, ()):
            return category, "definitive"
        if normalized in structured_labels.review_required.get(category, ()):
            return category, "review_required"
    return None, None


def _description_prohibited_fail(
    description: str,
    keyword_policy: SharedKeywordPolicy,
    prohibited_categories: Sequence[str],
) -> bool:
    lowered = description.lower()
    for item in keyword_policy.fail_patterns:
        if item.pattern not in lowered:
            continue
        if item.category in prohibited_categories:
            return True
    return False


def _segment_has_prohibited_revenue(
    segments: Sequence[BusinessRevenueEvidence],
) -> bool:
    for segment in segments:
        category = str(segment.category or "").lower()
        name = str(segment.segment_name or "").lower()
        if "non_permissible" not in category and "non_permissible" not in name:
            continue
        if segment.revenue_pct is not None and float(segment.revenue_pct) > 0:
            return True
        if segment.revenue_value is not None and float(segment.revenue_value) > 0:
            return True
    return False


def _unknown_segment_share(segments: Sequence[BusinessRevenueEvidence]) -> float:
    unknown_pct = 0.0
    unknown_value = 0.0
    total_value = 0.0
    has_pct = False
    for segment in segments:
        category = str(segment.category or "").lower()
        if category != "unknown":
            continue
        if segment.revenue_pct is not None:
            has_pct = True
            unknown_pct += float(segment.revenue_pct)
        if segment.revenue_value is not None:
            unknown_value += float(segment.revenue_value)
            total_value += float(segment.revenue_value)
    if has_pct:
        return unknown_pct
    if total_value > 0:
        return unknown_value / total_value * 100.0
    return 0.0


def evaluate_business_activity_coverage(
    evidence: BusinessActivityEvidence,
    *,
    methodology_id: str,
) -> BusinessActivityCoverageResult:
    rules = get_methodology_business_rules(methodology_id)
    if rules is None:
        return BusinessActivityCoverageResult(
            state=COVERAGE_INSUFFICIENT,
            limitations=("Methodology business rules not configured.",),
        )

    registry = load_business_rules_registry()
    structured_labels = registry.structured_sector_labels
    keyword_policy = registry.shared_keyword_policy
    prohibited_categories = rules.prohibited_categories
    sources: list[str] = []
    limitations: list[str] = []

    if _segment_has_prohibited_revenue(evidence.revenue_segments):
        return BusinessActivityCoverageResult(
            state=COVERAGE_PROHIBITED_FOUND,
            limitations=("Structured revenue segment indicates prohibited revenue.",),
            sources=("revenue_segments",),
        )

    sic_code = evidence.sic_code
    if sic_code is None or not str(sic_code).strip():
        limitations.append("SIC code missing.")
    elif not _trusted_source(evidence.source) and not evidence.evidence_refs:
        limitations.append("SIC code lacks trusted provenance.")
    else:
        sources.append("sic")
        mapped = resolve_sic_mapping(str(sic_code))
        if mapped is not None:
            category, strength = mapped
            if category in prohibited_categories and strength != "review_required":
                return BusinessActivityCoverageResult(
                    state=COVERAGE_PROHIBITED_FOUND,
                    limitations=(f"SIC {sic_code} maps to prohibited category {category}.",),
                    sources=("sic",),
                )

    if evidence.sector is None and evidence.industry is None:
        limitations.append("Structured sector/industry missing.")
    elif not _trusted_source(evidence.source) and not evidence.evidence_refs:
        limitations.append("Sector/industry lacks trusted provenance.")
    else:
        sources.append("structured_classification")
        for label in (evidence.sector, evidence.industry):
            category, strength = _structured_label_match(
                label,
                structured_labels,
                prohibited_categories,
            )
            if category is not None and strength == "definitive":
                return BusinessActivityCoverageResult(
                    state=COVERAGE_PROHIBITED_FOUND,
                    limitations=(f"Structured label maps to prohibited category {category}.",),
                    sources=("structured_classification",),
                )

    description = evidence.business_description
    if description is None or len(str(description).strip()) < _MIN_DESCRIPTION_CHARS:
        limitations.append("Issuer business description missing or too short.")
    else:
        sources.append("business_description")
        if _description_prohibited_fail(
            str(description),
            keyword_policy,
            prohibited_categories,
        ):
            return BusinessActivityCoverageResult(
                state=COVERAGE_PROHIBITED_FOUND,
                limitations=("Business description contains prohibited activity keywords.",),
                sources=("business_description",),
            )

    if evidence.reported_total_revenue is None or evidence.reported_total_revenue <= 0:
        limitations.append("Reported total revenue missing.")

    if evidence.revenue_segments:
        unknown_share = _unknown_segment_share(evidence.revenue_segments)
        if unknown_share >= 20.0:
            limitations.append("Unknown-classified revenue segments exceed coverage threshold.")

    required_present = (
        sic_code is not None
        and (evidence.sector is not None or evidence.industry is not None)
        and description is not None
        and len(str(description).strip()) >= _MIN_DESCRIPTION_CHARS
        and evidence.reported_total_revenue is not None
        and evidence.reported_total_revenue > 0
        and (
            _trusted_source(evidence.source)
            or bool(evidence.evidence_refs)
        )
    )
    if not required_present or limitations:
        return BusinessActivityCoverageResult(
            state=COVERAGE_INSUFFICIENT,
            limitations=tuple(dict.fromkeys(limitations)),
            sources=tuple(dict.fromkeys(sources)),
        )

    return BusinessActivityCoverageResult(
        state=COVERAGE_NO_PROHIBITED_SUFFICIENT,
        limitations=(
            "Sufficient business classification and description coverage; "
            "no prohibited activity evidence identified.",
        ),
        sources=tuple(dict.fromkeys(sources)),
    )
