"""Production-safe FUND18 evidence assembly.

Combines already-produced/read-only sources:

- FUND14A canonical scanner identities,
- current cached official KAP evidence packs,
- FUND16 candidate research,
- FUND17 portfolio-fit context,
- canonical Wealth OS portfolio facts.

This module performs no network access, capture, persistence, ranking,
recommendation, allocation, 8E decision, trade, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from services.turkiye_fund_current_evidence import filter_current_packs
from services.turkiye_fund_portfolio_fit_evidence_builder import (
    build_portfolio_fit_evidence,
)
from services.turkiye_fund_portfolio_fit_official_exposure import (
    load_official_candidate_exposures,
)
from services.turkiye_fund_portfolio_fit_portfolio_evidence import (
    build_canonical_portfolio_fit_inputs,
)
from services.turkiye_fund_source_capture import load_cached_evidence_packs


class ProductionPortfolioFitEvidenceError(ValueError):
    """Fail-closed FUND18 production evidence assembly error."""


@dataclass(frozen=True)
class _ArtifactIdentity:
    fund_code: str
    kap_disclosure_index: int


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionPortfolioFitEvidenceError(f"{field}_must_be_object")
    return dict(value)


def _fund16_codes(fund16: Mapping[str, Any]) -> tuple[str, ...]:
    categories = fund16.get("categories")

    if not isinstance(categories, list):
        raise ProductionPortfolioFitEvidenceError(
            "fund16_categories_must_be_list"
        )

    codes: list[str] = []

    for category in categories:
        if not isinstance(category, Mapping):
            continue

        candidates = category.get("candidates")

        if not isinstance(candidates, list):
            continue

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue

            code = str(candidate.get("fund_code") or "").strip().upper()

            if code and code not in codes:
                codes.append(code)

    if not codes:
        raise ProductionPortfolioFitEvidenceError(
            "fund16_candidate_set_empty"
        )

    return tuple(codes)


def _fund14a_identities(
    fund14a: Mapping[str, Any],
) -> tuple[_ArtifactIdentity, ...]:
    if fund14a.get("schema_version") != "fund14a_research_snapshot_3":
        raise ProductionPortfolioFitEvidenceError(
            "unsupported_fund14a_schema"
        )

    if fund14a.get("research_only") is not True:
        raise ProductionPortfolioFitEvidenceError(
            "fund14a_research_only_not_true"
        )

    scanner = _object(fund14a.get("scanner"), "fund14a_scanner")

    if scanner.get("persist") is not False:
        raise ProductionPortfolioFitEvidenceError(
            "fund14a_scanner_persist_not_false"
        )

    for field in (
        "eight_e_calls",
        "new_money_calls",
        "trades",
        "portfolio_writes",
    ):
        if scanner.get(field) != 0:
            raise ProductionPortfolioFitEvidenceError(
                f"fund14a_execution_firewall_failed:{field}"
            )

    identities = scanner.get("identities")

    if not isinstance(identities, list) or not identities:
        raise ProductionPortfolioFitEvidenceError(
            "fund14a_identities_missing"
        )

    result: list[_ArtifactIdentity] = []

    for raw in identities:
        if not isinstance(raw, Mapping):
            continue

        code = str(raw.get("fund_code") or "").strip().upper()

        if not code:
            continue

        result.append(
            _ArtifactIdentity(
                fund_code=code,
                kap_disclosure_index=int(
                    raw.get("kap_disclosure_index") or 0
                ),
            )
        )

    if not result:
        raise ProductionPortfolioFitEvidenceError(
            "fund14a_identity_set_empty"
        )

    return tuple(result)


def build_production_portfolio_fit_evidence(
    fund14a: Mapping[str, Any],
    fund16: Mapping[str, Any],
    fund17: Mapping[str, Any],
    portfolio_view: Any,
    *,
    evidence_packs: Mapping[str, Mapping[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build factual FUND18 evidence from production-safe read-only inputs."""

    identities = _fund14a_identities(fund14a)
    candidate_codes = _fund16_codes(fund16)

    packs = (
        dict(evidence_packs)
        if evidence_packs is not None
        else load_cached_evidence_packs()
    )

    current_packs, quarantined = filter_current_packs(
        packs,
        identities,
    )

    candidate_exposures = load_official_candidate_exposures(
        candidate_codes,
        evidence_packs=current_packs,
    )

    portfolio_inputs = build_canonical_portfolio_fit_inputs(
        portfolio_view,
        candidate_codes,
    )

    evidence = build_portfolio_fit_evidence(
        fund16,
        fund17,
        candidate_exposures=candidate_exposures,
        portfolio_exposure=portfolio_inputs["portfolio_exposure"],
        portfolio_weights=portfolio_inputs["portfolio_weights"],
        generated_at=generated_at,
    )

    portfolio_context = fund17.get("portfolio_context")
    desired_roles: list[str] = []

    if isinstance(portfolio_context, Mapping):
        raw_roles = portfolio_context.get("desired_roles")
        if isinstance(raw_roles, list):
            desired_roles = [
                str(role).strip()
                for role in raw_roles
                if str(role).strip()
            ]

    return {
        "evidence": evidence,
        "assessment_inputs": {
            "candidate_exposures": candidate_exposures,
            "portfolio_exposure": portfolio_inputs["portfolio_exposure"],
            "portfolio_weights": portfolio_inputs["portfolio_weights"],
            "desired_roles": desired_roles,
        },
        "diagnostics": {
            "candidate_codes": list(candidate_codes),
            "candidate_count": len(candidate_codes),
            "current_pack_count": len(current_packs),
            "quarantined_codes": list(quarantined),
            "official_exposure_codes": sorted(candidate_exposures),
            "portfolio_weight_codes": sorted(
                portfolio_inputs["portfolio_weights"]
            ),
            "research_only": True,
            "execution_authority": False,
            "production_persist": False,
            "network_calls": 0,
            "capture_calls": 0,
            "production_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
            "trade_actions": 0,
        },
    }
