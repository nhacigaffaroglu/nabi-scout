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
from services.participation_methodology_registry import (
    get_default_equity_methodology,
    get_default_equity_methodology_id,
    get_default_equity_methodology_version,
    get_methodology,
    list_methodologies,
    list_methodology_versions,
)
from services.participation_screening_context import VALID_SCREENING_CONTEXTS


@dataclass(frozen=True)
class MethodologyAuditIssue:
    code: str
    message: str


@dataclass(frozen=True)
class MethodologyAuditResult:
    methodology_id: str
    methodology_version: str
    ok: bool
    issues: Tuple[MethodologyAuditIssue, ...] = field(default_factory=tuple)


def _audit_active_version_consistency() -> list[MethodologyAuditIssue]:
    issues: list[MethodologyAuditIssue] = []
    default_id = get_default_equity_methodology_id()
    default_version = get_default_equity_methodology_version()
    active = get_methodology(default_id)
    if active is None:
        issues.append(
            MethodologyAuditIssue(
                "missing_active_methodology",
                "Default equity methodology is not configured.",
            )
        )
        return issues
    if active.version != default_version:
        issues.append(
            MethodologyAuditIssue(
                "stale_active_version",
                (
                    f"Active methodology version {active.version} does not match "
                    f"default_equity_methodology_version {default_version}."
                ),
            )
        )
    if active.archived:
        issues.append(
            MethodologyAuditIssue(
                "archived_active_methodology",
                "Default active methodology is marked archived.",
            )
        )
    if not active.effective_date:
        issues.append(
            MethodologyAuditIssue(
                "missing_effective_date",
                "Active methodology missing effective_date.",
            )
        )
    if not active.source_reference:
        issues.append(
            MethodologyAuditIssue(
                "missing_source_reference",
                "Active methodology missing source_reference.",
            )
        )
    if not active.source_documents:
        issues.append(
            MethodologyAuditIssue(
                "missing_source_documents",
                "Active methodology missing source_documents metadata.",
            )
        )
    if active.version == "2024-10" and default_version != "2024-10":
        issues.append(
            MethodologyAuditIssue(
                "stale_version_active",
                "2024-10 is still active while a newer default version is configured.",
            )
        )
    return issues


def audit_methodology(
    methodology_id: str,
    *,
    version: str | None = None,
) -> MethodologyAuditResult:
    issues: list[MethodologyAuditIssue] = []
    methodology = get_methodology(methodology_id, version=version)
    if methodology is None:
        return MethodologyAuditResult(
            methodology_id=methodology_id,
            methodology_version=version or "",
            ok=False,
            issues=(
                MethodologyAuditIssue(
                    "unknown_methodology",
                    "Methodology not in registry.",
                ),
            ),
        )

    default = get_default_equity_methodology()
    if (
        methodology.methodology_id == default.methodology_id
        and methodology.version == default.version
    ):
        issues.extend(_audit_active_version_consistency())

    if not methodology.version:
        issues.append(MethodologyAuditIssue("missing_version", "Methodology version missing."))
    if methodology.active and not methodology.effective_date:
        issues.append(
            MethodologyAuditIssue(
                "missing_effective_date",
                f"Active methodology {methodology.version} missing effective_date.",
            )
        )

    rule_ids: set[str] = set()
    for rule in methodology.rules:
        if rule.rule_id in rule_ids:
            issues.append(
                MethodologyAuditIssue("duplicate_rule_id", f"Duplicate rule id: {rule.rule_id}")
            )
        rule_ids.add(rule.rule_id)
        if resolve_rule_threshold_present(rule) is False:
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
        if methodology.methodology_id == "msci_islamic_index_series" and methodology.active:
            if rule.rule_id.endswith("receivables_and_cash_to_total_assets"):
                if rule.entry_buffer_pct != 46.0 or rule.financial_ratio_threshold_pct != 70.0:
                    issues.append(
                        MethodologyAuditIssue(
                            "receivables_threshold_mismatch",
                            "MSCI receivables+cash thresholds do not match official 46/70 tiers.",
                        )
                    )
            if (
                rule.exit_buffer_pct is not None
                and rule.rule_id.endswith("receivables_and_cash_to_total_assets")
            ):
                issues.append(
                    MethodologyAuditIssue(
                        "unsupported_exit_buffer",
                        "Receivables+cash rule must not define an exit buffer.",
                    )
                )

    business_rules = get_methodology_business_rules(methodology_id)
    if business_rules is None:
        issues.append(
            MethodologyAuditIssue("missing_business_rules", "No business rules configured.")
        )
    elif business_rules.version != methodology.version and methodology.active:
        issues.append(
            MethodologyAuditIssue(
                "business_version_mismatch",
                (
                    f"Business rules version {business_rules.version} "
                    f"does not match financial registry {methodology.version}."
                ),
            )
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

    if methodology.active and methodology.default_screening_context not in VALID_SCREENING_CONTEXTS:
        issues.append(
            MethodologyAuditIssue(
                "invalid_default_screening_context",
                f"Invalid default_screening_context: {methodology.default_screening_context}",
            )
        )

    return MethodologyAuditResult(
        methodology_id=methodology_id,
        methodology_version=methodology.version,
        ok=not issues,
        issues=tuple(issues),
    )


def resolve_rule_threshold_present(rule) -> bool:
    if rule.threshold_pct is not None:
        return True
    if rule.screening_context_thresholds:
        return True
    if rule.entry_buffer_pct is not None or rule.financial_ratio_threshold_pct is not None:
        return True
    return False


def audit_all_methodologies() -> Tuple[MethodologyAuditResult, ...]:
    default = get_default_equity_methodology()
    active_ids = {item.methodology_id for item in list_methodologies()}
    results: list[MethodologyAuditResult] = [
        audit_methodology(default.methodology_id, version=default.version)
    ]
    for item in list_methodology_versions(default.methodology_id):
        if item.archived:
            results.append(audit_methodology(item.methodology_id, version=item.version))
    for methodology_id in sorted(active_ids):
        if methodology_id == default.methodology_id:
            continue
        methodology = get_methodology(methodology_id)
        if methodology is not None:
            results.append(audit_methodology(methodology_id, version=methodology.version))
    return tuple(results)
