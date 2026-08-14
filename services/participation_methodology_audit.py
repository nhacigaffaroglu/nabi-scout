from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from services.participation_business_rules_registry import (
    get_methodology_business_rules,
    load_business_rules_registry,
    load_sic_mappings,
)
from services.participation_financial_engine import (
    DENOMINATOR_REGISTRY_TO_FIELD,
    NUMERATOR_RESOLVERS,
)
from services.participation_methodology_registry import get_methodology, list_methodologies


@dataclass(frozen=True)
class MethodologyAuditIssue:
    code: str
    message: str


@dataclass(frozen=True)
class MethodologyAuditResult:
    methodology_id: str
    ok: bool
    issues: Tuple[MethodologyAuditIssue, ...] = field(default_factory=tuple)


def audit_methodology(methodology_id: str) -> MethodologyAuditResult:
    business_registry = load_business_rules_registry()
    issues: list[MethodologyAuditIssue] = []

    methodology = get_methodology(methodology_id)
    if methodology is None:
        return MethodologyAuditResult(
            methodology_id=methodology_id,
            ok=False,
            issues=(MethodologyAuditIssue("unknown_methodology", "Methodology not in registry."),),
        )

    if not methodology.version:
        issues.append(MethodologyAuditIssue("missing_version", "Methodology version missing."))

    rule_ids: set[str] = set()
    for rule in methodology.rules:
        if rule.rule_id in rule_ids:
            issues.append(
                MethodologyAuditIssue("duplicate_rule_id", f"Duplicate rule id: {rule.rule_id}")
            )
        rule_ids.add(rule.rule_id)
        if rule.threshold_pct is None:
            issues.append(
                MethodologyAuditIssue("missing_threshold", f"Missing threshold: {rule.rule_id}")
            )
        if rule.numerator not in NUMERATOR_RESOLVERS:
            issues.append(
                MethodologyAuditIssue(
                    "missing_numerator_resolver",
                    f"No numerator resolver for {rule.rule_id}: {rule.numerator}",
                )
            )
        if rule.denominator not in DENOMINATOR_REGISTRY_TO_FIELD:
            issues.append(
                MethodologyAuditIssue(
                    "missing_denominator_mapping",
                    f"No denominator mapping for {rule.rule_id}: {rule.denominator}",
                )
            )

    business_rules = business_registry.methodologies.get(methodology_id)
    if business_rules is None:
        issues.append(
            MethodologyAuditIssue("missing_business_rules", "No business rules configured.")
        )
    else:
        for revenue_rule in business_rules.revenue_rules:
            if revenue_rule.linked_registry_rule_id not in rule_ids:
                issues.append(
                    MethodologyAuditIssue(
                        "orphan_revenue_rule",
                        f"Revenue rule {revenue_rule.rule_id} links to missing financial rule.",
                    )
                )

    if methodology.financial_screen_complete_methodology:
        for rule in methodology.rules:
            if rule.numerator not in NUMERATOR_RESOLVERS:
                issues.append(
                    MethodologyAuditIssue(
                        "complete_flag_mismatch",
                        f"financial_screen_complete_methodology=true but {rule.rule_id} not executable.",
                    )
                )
            if rule.denominator not in DENOMINATOR_REGISTRY_TO_FIELD:
                issues.append(
                    MethodologyAuditIssue(
                        "complete_flag_mismatch",
                        f"financial_screen_complete_methodology=true but denominator missing for {rule.rule_id}.",
                    )
                )

    if business_rules and business_rules.business_screen_complete_methodology:
        if not load_sic_mappings():
            issues.append(
                MethodologyAuditIssue(
                    "complete_flag_mismatch",
                    "business_screen_complete_methodology=true but SIC mapping empty.",
                )
            )

    return MethodologyAuditResult(
        methodology_id=methodology_id,
        ok=not issues,
        issues=tuple(issues),
    )


def audit_all_methodologies() -> Tuple[MethodologyAuditResult, ...]:
    return tuple(audit_methodology(item.methodology_id) for item in list_methodologies())
