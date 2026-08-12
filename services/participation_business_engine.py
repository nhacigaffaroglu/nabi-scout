from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from services.participation_business_contract import (
    BUSINESS_SCREEN_OUTCOME_FAIL,
    BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA,
    BUSINESS_SCREEN_OUTCOME_PASS,
    BUSINESS_SCREEN_OUTCOME_REVIEW_REQUIRED,
    EVIDENCE_COMPLETENESS_COMPLETE,
    EVIDENCE_COMPLETENESS_NONE,
    EVIDENCE_COMPLETENESS_PARTIAL,
    EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
    EVIDENCE_TYPE_REVENUE_SEGMENT,
    EVIDENCE_TYPE_SIC,
    EVIDENCE_TYPE_STRUCTURED_INDUSTRY,
    EVIDENCE_TYPE_STRUCTURED_SECTOR,
    BusinessActivityEvidence,
    BusinessActivityRuleResult,
    BusinessActivityScreenResult,
    BusinessRevenueEvidence,
)
from services.participation_business_rules_registry import (
    KeywordPattern,
    MethodologyBusinessRules,
    RevenueRuleDefinition,
    SharedKeywordPolicy,
    StructuredSectorLabels,
    get_methodology_business_rules,
    load_business_rules_registry,
    resolve_sic_mapping,
)
from services.participation_financial_engine import normalize_financial_value
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)

SUPPORTED_COMPARATORS = frozenset({"<", "<=", ">", ">="})


def _normalize_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _compare_ratio(
    ratio_pct: Decimal,
    threshold_pct: Decimal,
    comparator: str,
) -> str:
    if comparator == "<":
        return RULE_OUTCOME_PASS if ratio_pct < threshold_pct else RULE_OUTCOME_FAIL
    if comparator == "<=":
        return RULE_OUTCOME_PASS if ratio_pct <= threshold_pct else RULE_OUTCOME_FAIL
    if comparator == ">":
        return RULE_OUTCOME_PASS if ratio_pct > threshold_pct else RULE_OUTCOME_FAIL
    if comparator == ">=":
        return RULE_OUTCOME_PASS if ratio_pct >= threshold_pct else RULE_OUTCOME_FAIL
    return RULE_OUTCOME_INSUFFICIENT_DATA


def _negated_match(text: str, pattern: str, negation_patterns: Sequence[str]) -> bool:
    lowered = text.lower()
    index = lowered.find(pattern)
    if index < 0:
        return False
    prefix = lowered[max(0, index - 40):index]
    if any(neg in prefix for neg in negation_patterns):
        return True
    suffix = lowered[index + len(pattern): index + len(pattern) + 8]
    if suffix.startswith("-free") or suffix.startswith(" free"):
        return True
    return False


def _find_keyword_matches(
    description: str,
    patterns: Sequence[KeywordPattern],
    negation_patterns: Sequence[str],
) -> List[KeywordPattern]:
    matches: list[KeywordPattern] = []
    lowered = description.lower()
    for item in patterns:
        if item.pattern not in lowered:
            continue
        if _negated_match(description, item.pattern, negation_patterns):
            continue
        matches.append(item)
    return matches


def _evaluate_sic_rule(
    rules: MethodologyBusinessRules,
    evidence: BusinessActivityEvidence,
) -> BusinessActivityRuleResult:
    sic_code = evidence.sic_code
    if sic_code is None or not str(sic_code).strip():
        return BusinessActivityRuleResult(
            rule_id=rules.sic_rule_id,
            category="sic_exclusion",
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_SIC,
            confidence=CONFIDENCE_LOW,
            warnings=("SIC code not provided.",),
        )

    mapped = resolve_sic_mapping(sic_code)
    if mapped is None:
        return BusinessActivityRuleResult(
            rule_id=rules.sic_rule_id,
            category="sic_exclusion",
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_SIC,
            matched_values=(str(sic_code),),
            source_refs=(("sic_code", str(sic_code)),),
            confidence=CONFIDENCE_LOW,
            warnings=("SIC code is not mapped to a prohibited category.",),
        )

    mapped_category, match_strength = mapped
    if mapped_category not in rules.prohibited_categories:
        return BusinessActivityRuleResult(
            rule_id=rules.sic_rule_id,
            category="sic_exclusion",
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_SIC,
            matched_values=(str(sic_code), mapped_category),
            source_refs=(
                ("sic_code", str(sic_code)),
                ("mapped_category", mapped_category),
            ),
            confidence=CONFIDENCE_LOW,
            warnings=(
                f"SIC maps to '{mapped_category}' which is outside this methodology scope.",
            ),
        )

    if match_strength == "review_required":
        return BusinessActivityRuleResult(
            rule_id=rules.sic_rule_id,
            category=mapped_category,
            outcome=RULE_OUTCOME_REVIEW_REQUIRED,
            evidence_type=EVIDENCE_TYPE_SIC,
            matched_values=(str(sic_code), mapped_category),
            source_refs=(
                ("sic_code", str(sic_code)),
                ("mapped_category", mapped_category),
                ("match_strength", match_strength),
            ),
            confidence=CONFIDENCE_MEDIUM,
            warnings=(f"SIC {sic_code} maps to broad category '{mapped_category}'; review required.",),
        )

    return BusinessActivityRuleResult(
        rule_id=rules.sic_rule_id,
        category=mapped_category,
        outcome=RULE_OUTCOME_FAIL,
        evidence_type=EVIDENCE_TYPE_SIC,
        matched_values=(str(sic_code), mapped_category),
        source_refs=(
            ("sic_code", str(sic_code)),
            ("mapped_category", mapped_category),
            ("match_strength", match_strength),
        ),
        confidence=CONFIDENCE_HIGH,
        warnings=(f"SIC {sic_code} maps to prohibited category '{mapped_category}'.",),
    )


def _structured_label_match(
    label: Optional[str],
    structured_labels: StructuredSectorLabels,
    prohibited_categories: Sequence[str],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    normalized = _normalize_label(label)
    if normalized is None:
        return None, None, None
    for category in prohibited_categories:
        if normalized in structured_labels.definitive.get(category, ()):
            return category, normalized, "definitive"
        if normalized in structured_labels.review_required.get(category, ()):
            return category, normalized, "review_required"
    return None, None, None


def _structured_outcome_for_match(
    match_strength: str,
) -> str:
    if match_strength == "definitive":
        return RULE_OUTCOME_FAIL
    return RULE_OUTCOME_REVIEW_REQUIRED


def _evaluate_structured_sector_rule(
    rules: MethodologyBusinessRules,
    evidence: BusinessActivityEvidence,
    structured_labels: StructuredSectorLabels,
) -> BusinessActivityRuleResult:
    sector_match = _structured_label_match(
        evidence.sector,
        structured_labels,
        rules.prohibited_categories,
    )
    industry_match = _structured_label_match(
        evidence.industry,
        structured_labels,
        rules.prohibited_categories,
    )

    for match, evidence_type, source_field, source_value in (
        (sector_match, EVIDENCE_TYPE_STRUCTURED_SECTOR, "sector", evidence.sector),
        (industry_match, EVIDENCE_TYPE_STRUCTURED_INDUSTRY, "industry", evidence.industry),
    ):
        category, matched, strength = match
        if category is None:
            continue
        outcome = _structured_outcome_for_match(str(strength))
        confidence = CONFIDENCE_HIGH if strength == "definitive" else CONFIDENCE_MEDIUM
        warning = (
            f"Structured {source_field} '{matched}' maps to prohibited category."
            if outcome == RULE_OUTCOME_FAIL
            else f"Structured {source_field} '{matched}' requires manual review."
        )
        return BusinessActivityRuleResult(
            rule_id=rules.sector_rule_id,
            category=str(category),
            outcome=outcome,
            evidence_type=evidence_type,
            matched_values=(matched,),
            source_refs=((source_field, str(source_value)), ("match_strength", str(strength))),
            confidence=confidence,
            warnings=(warning,),
        )

    if evidence.sector is None and evidence.industry is None:
        return BusinessActivityRuleResult(
            rule_id=rules.sector_rule_id,
            category="structured_classification",
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_STRUCTURED_SECTOR,
            confidence=CONFIDENCE_LOW,
            warnings=("Structured sector/industry evidence not provided.",),
        )

    return BusinessActivityRuleResult(
        rule_id=rules.sector_rule_id,
        category="structured_classification",
        outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
        evidence_type=EVIDENCE_TYPE_STRUCTURED_SECTOR,
        matched_values=tuple(
            value
            for value in (_normalize_label(evidence.sector), _normalize_label(evidence.industry))
            if value
        ),
        source_refs=tuple(
            ref
            for ref in (
                ("sector", str(evidence.sector)) if evidence.sector else None,
                ("industry", str(evidence.industry)) if evidence.industry else None,
            )
            if ref is not None
        ),
        confidence=CONFIDENCE_LOW,
        warnings=(
            "Structured label present but does not establish business-screen PASS; "
            "absence of prohibited label match is not PASS evidence.",
        ),
    )


def _evaluate_description_rule(
    rules: MethodologyBusinessRules,
    evidence: BusinessActivityEvidence,
    keyword_policy: SharedKeywordPolicy,
) -> BusinessActivityRuleResult:
    description = evidence.business_description
    if description is None or not str(description).strip():
        return BusinessActivityRuleResult(
            rule_id=rules.description_rule_id,
            category="description_keyword",
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
            confidence=CONFIDENCE_LOW,
            warnings=("Business description not provided.",),
        )

    fail_matches = _find_keyword_matches(
        description,
        keyword_policy.fail_patterns,
        keyword_policy.negation_patterns,
    )
    prohibited_fail = [
        match
        for match in fail_matches
        if match.category in rules.prohibited_categories
    ]
    if prohibited_fail:
        match = prohibited_fail[0]
        return BusinessActivityRuleResult(
            rule_id=rules.description_rule_id,
            category=match.category,
            outcome=RULE_OUTCOME_FAIL,
            evidence_type=EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
            matched_values=(match.pattern,),
            source_refs=(("description_excerpt", description[:120]),),
            confidence=CONFIDENCE_MEDIUM,
            warnings=("Explicit description keyword indicates prohibited activity.",),
        )

    review_matches = _find_keyword_matches(
        description,
        keyword_policy.review_patterns,
        keyword_policy.negation_patterns,
    )
    prohibited_review = [
        match
        for match in review_matches
        if match.category in rules.prohibited_categories
    ]
    if prohibited_review:
        match = prohibited_review[0]
        if match.category == "weapons_defense" and re.search(
            r"defense against|cyber defense|defence against",
            description,
            flags=re.IGNORECASE,
        ):
            return BusinessActivityRuleResult(
                rule_id=rules.description_rule_id,
                category="description_keyword",
                outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
                evidence_type=EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
                matched_values=(match.pattern,),
                source_refs=(("description_excerpt", description[:120]),),
                confidence=CONFIDENCE_LOW,
                warnings=("Ambiguous defense wording; not treated as weapons exclusion.",),
            )
        return BusinessActivityRuleResult(
            rule_id=rules.description_rule_id,
            category=match.category,
            outcome=RULE_OUTCOME_REVIEW_REQUIRED,
            evidence_type=EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
            matched_values=(match.pattern,),
            source_refs=(("description_excerpt", description[:120]),),
            confidence=CONFIDENCE_LOW,
            warnings=("Ambiguous description keyword requires manual review.",),
        )

    return BusinessActivityRuleResult(
        rule_id=rules.description_rule_id,
        category="description_keyword",
        outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
        evidence_type=EVIDENCE_TYPE_DESCRIPTION_KEYWORD,
        confidence=CONFIDENCE_LOW,
        warnings=(
            "No prohibited description keyword matched; absence of keyword is not PASS evidence.",
        ),
    )


def _segment_matches_categories(
    segment: BusinessRevenueEvidence,
    categories: Sequence[str],
) -> bool:
    segment_category = _normalize_label(segment.category) or ""
    segment_name = _normalize_label(segment.segment_name) or ""
    for category in categories:
        normalized = category.lower()
        if normalized in segment_category or normalized in segment_name:
            return True
    return False


def _sum_revenue_segments(
    segments: Sequence[BusinessRevenueEvidence],
    categories: Sequence[str],
) -> Tuple[Optional[Decimal], bool]:
    matched_values: list[Decimal] = []
    has_pct = False
    for segment in segments:
        if not _segment_matches_categories(segment, categories):
            continue
        if segment.revenue_pct is not None:
            has_pct = True
            value = normalize_financial_value(segment.revenue_pct)
            if value is not None:
                matched_values.append(value)
        elif segment.revenue_value is not None:
            value = normalize_financial_value(segment.revenue_value)
            if value is not None:
                matched_values.append(value)
    if not matched_values:
        return None, has_pct
    return sum(matched_values, Decimal("0")), has_pct


def _evaluate_revenue_rule(
    rule: RevenueRuleDefinition,
    evidence: BusinessActivityEvidence,
) -> BusinessActivityRuleResult:
    if not evidence.revenue_segments:
        return BusinessActivityRuleResult(
            rule_id=rule.rule_id,
            category=rule.category,
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_REVENUE_SEGMENT,
            threshold_pct=rule.threshold_pct,
            comparator=rule.comparator,
            confidence=CONFIDENCE_LOW,
            warnings=("Explicit revenue segment evidence not provided.",),
        )

    numerator_total, has_pct = _sum_revenue_segments(
        evidence.revenue_segments,
        rule.numerator_categories,
    )
    if numerator_total is None:
        return BusinessActivityRuleResult(
            rule_id=rule.rule_id,
            category=rule.category,
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            evidence_type=EVIDENCE_TYPE_REVENUE_SEGMENT,
            threshold_pct=rule.threshold_pct,
            comparator=rule.comparator,
            confidence=CONFIDENCE_LOW,
            warnings=("No explicit revenue values for prohibited categories.",),
        )

    if has_pct:
        ratio_pct = numerator_total
        outcome = _compare_ratio(
            ratio_pct,
            Decimal(str(rule.threshold_pct)),
            rule.comparator,
        )
        return BusinessActivityRuleResult(
            rule_id=rule.rule_id,
            category=rule.category,
            outcome=outcome,
            evidence_type=EVIDENCE_TYPE_REVENUE_SEGMENT,
            matched_values=tuple(
                segment.segment_name
                for segment in evidence.revenue_segments
                if _segment_matches_categories(segment, rule.numerator_categories)
            ),
            source_refs=(("denominator_field", rule.denominator_field),),
            confidence=CONFIDENCE_HIGH,
            threshold_pct=rule.threshold_pct,
            comparator=rule.comparator,
            ratio_pct=float(ratio_pct),
        )

    return BusinessActivityRuleResult(
        rule_id=rule.rule_id,
        category=rule.category,
        outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
        evidence_type=EVIDENCE_TYPE_REVENUE_SEGMENT,
        threshold_pct=rule.threshold_pct,
        comparator=rule.comparator,
        confidence=CONFIDENCE_MEDIUM,
        warnings=(
            "Revenue values without explicit percentages cannot be threshold-tested in 6B.2d.",
        ),
    )


def aggregate_business_outcomes(
    rule_results: Sequence[BusinessActivityRuleResult],
) -> str:
    if not rule_results:
        return BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA

    outcomes = {rule.outcome for rule in rule_results}
    if RULE_OUTCOME_FAIL in outcomes:
        return BUSINESS_SCREEN_OUTCOME_FAIL
    if RULE_OUTCOME_REVIEW_REQUIRED in outcomes:
        return BUSINESS_SCREEN_OUTCOME_REVIEW_REQUIRED
    if RULE_OUTCOME_INSUFFICIENT_DATA in outcomes:
        return BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA

    evaluated = [
        rule
        for rule in rule_results
        if rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
    ]
    if evaluated and all(rule.outcome == RULE_OUTCOME_PASS for rule in evaluated):
        return BUSINESS_SCREEN_OUTCOME_PASS
    return BUSINESS_SCREEN_OUTCOME_REVIEW_REQUIRED


def _evidence_completeness(
    rule_results: Sequence[BusinessActivityRuleResult],
) -> str:
    if not rule_results:
        return EVIDENCE_COMPLETENESS_NONE
    insufficient = sum(
        1 for rule in rule_results if rule.outcome == RULE_OUTCOME_INSUFFICIENT_DATA
    )
    if insufficient == len(rule_results):
        return EVIDENCE_COMPLETENESS_NONE
    if insufficient > 0:
        return EVIDENCE_COMPLETENESS_PARTIAL
    return EVIDENCE_COMPLETENESS_COMPLETE


def _methodology_complete_from_business_evaluation(
    rules: MethodologyBusinessRules,
    *,
    business_rules_evaluated: bool,
    overall_outcome: str,
    rule_results: Sequence[BusinessActivityRuleResult],
) -> bool:
    if not rules.business_screen_complete_methodology:
        return False
    return (
        business_rules_evaluated
        and overall_outcome == BUSINESS_SCREEN_OUTCOME_PASS
        and all(rule.outcome == RULE_OUTCOME_PASS for rule in rule_results)
    )


def evaluate_business_activity(
    methodology_id: str,
    evidence: BusinessActivityEvidence,
) -> BusinessActivityScreenResult:
    rules = get_methodology_business_rules(methodology_id)
    if rules is None:
        raise ValueError(f"No business rules configured for methodology_id: {methodology_id}")

    registry = load_business_rules_registry()
    rule_results: list[BusinessActivityRuleResult] = [
        _evaluate_sic_rule(rules, evidence),
        _evaluate_structured_sector_rule(
            rules,
            evidence,
            registry.structured_sector_labels,
        ),
        _evaluate_description_rule(rules, evidence, registry.shared_keyword_policy),
    ]
    for revenue_rule in rules.revenue_rules:
        rule_results.append(_evaluate_revenue_rule(revenue_rule, evidence))

    overall_outcome = aggregate_business_outcomes(rule_results)
    business_rules_evaluated = any(
        rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL, RULE_OUTCOME_REVIEW_REQUIRED}
        for rule in rule_results
    )
    methodology_complete = _methodology_complete_from_business_evaluation(
        rules,
        business_rules_evaluated=business_rules_evaluated,
        overall_outcome=overall_outcome,
        rule_results=rule_results,
    )

    warnings: list[str] = list(evidence.warnings)
    if business_rules_evaluated and not methodology_complete:
        warnings.append(
            "Business rule subset evaluated; full methodology business completeness is not claimed."
        )
    if overall_outcome == BUSINESS_SCREEN_OUTCOME_INSUFFICIENT_DATA:
        warnings.append(
            "Insufficient business activity evidence; absence of prohibited signals is not PASS."
        )

    return BusinessActivityScreenResult(
        symbol=evidence.symbol,
        methodology_id=methodology_id,
        methodology_version=rules.version,
        rule_results=tuple(rule_results),
        overall_outcome=overall_outcome,
        evidence_completeness=_evidence_completeness(rule_results),
        business_rules_evaluated=business_rules_evaluated,
        methodology_complete=methodology_complete,
        as_of_date=evidence.source_date,
        warnings=tuple(dict.fromkeys(warnings)),
    )
