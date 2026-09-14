"""Production-safe FUND18 portfolio-fit evidence builder.

Builds provenance-backed FUND18 evidence from existing research and portfolio
facts. It does not derive portfolio-fit assessments, rank candidates, make
recommendations, allocate capital, persist production data, or execute trades.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.turkiye_fund_portfolio_fit_evidence import (
    DIMENSIONS,
    EVIDENCE_SCHEMA,
    normalize_candidate_evidence,
)


ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


class PortfolioFitEvidenceBuilderError(ValueError):
    """Fail-closed production evidence-builder error."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_source_as_of(value: Any, fallback: str) -> str:
    """Normalize official source periods to the FUND18 ISO-8601 contract."""

    raw = str(value or "").strip()
    if not raw:
        return fallback

    if len(raw) == 7 and raw[4] == "-":
        try:
            year = int(raw[:4])
            month = int(raw[5:7])
            last_day = monthrange(year, month)[1]
        except (ValueError, IndexError):
            return raw

        return f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"

    return raw


def _candidate_rows(fund16: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if fund16.get("schema_version") != "fund16_category_comparison_artifact_1":
        raise PortfolioFitEvidenceBuilderError("invalid_fund16_schema")
    if fund16.get("research_only") is not True:
        raise PortfolioFitEvidenceBuilderError("fund16_not_research_only")
    if fund16.get("execution_authority") is not False:
        raise PortfolioFitEvidenceBuilderError("fund16_execution_authority")
    if fund16.get("production_persist") is not False:
        raise PortfolioFitEvidenceBuilderError("fund16_production_persist")

    rows: dict[str, Mapping[str, Any]] = {}
    categories = fund16.get("categories")
    if not isinstance(categories, list):
        raise PortfolioFitEvidenceBuilderError("fund16_categories_invalid")

    for category in categories:
        if not isinstance(category, Mapping):
            raise PortfolioFitEvidenceBuilderError("fund16_category_invalid")
        candidates = category.get("candidates")
        if not isinstance(candidates, list):
            raise PortfolioFitEvidenceBuilderError("fund16_candidates_invalid")
        for row in candidates:
            if not isinstance(row, Mapping):
                raise PortfolioFitEvidenceBuilderError("fund16_candidate_invalid")
            code = str(row.get("fund_code") or "").strip().upper()
            if not code:
                raise PortfolioFitEvidenceBuilderError("fund16_candidate_code_missing")
            if code in rows:
                raise PortfolioFitEvidenceBuilderError(
                    f"fund16_duplicate_candidate:{code}"
                )
            rows[code] = row
    return rows


def _fund17_codes(fund17: Mapping[str, Any]) -> tuple[str, ...]:
    if fund17.get("schema_version") != "fund17_portfolio_fit_artifact_1":
        raise PortfolioFitEvidenceBuilderError("invalid_fund17_schema")
    if fund17.get("research_only") is not True:
        raise PortfolioFitEvidenceBuilderError("fund17_not_research_only")
    if fund17.get("execution_authority") is not False:
        raise PortfolioFitEvidenceBuilderError("fund17_execution_authority")
    if fund17.get("production_persist") is not False:
        raise PortfolioFitEvidenceBuilderError("fund17_production_persist")
    if fund17.get("portfolio_context_available") is not True:
        raise PortfolioFitEvidenceBuilderError("portfolio_context_required")

    candidates = fund17.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise PortfolioFitEvidenceBuilderError("fund17_candidates_invalid")

    codes = []
    for row in candidates:
        if not isinstance(row, Mapping):
            raise PortfolioFitEvidenceBuilderError("fund17_candidate_invalid")
        code = str(row.get("fund_code") or "").strip().upper()
        if not code:
            raise PortfolioFitEvidenceBuilderError("fund17_candidate_code_missing")
        codes.append(code)

    if len(set(codes)) != len(codes):
        raise PortfolioFitEvidenceBuilderError("fund17_duplicate_candidate")
    return tuple(codes)


def _source(
    *,
    source_type: str,
    source_id: str,
    observed_fact: str,
    as_of: str,
    claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_type": source_type,
        "source_id": source_id,
        "observed_fact": observed_fact,
        "as_of": as_of,
    }
    if claim is not None:
        row["claim"] = dict(claim)
    return row


def _dimension(
    sources: Sequence[Mapping[str, Any]],
    *,
    rationale: str,
) -> dict[str, Any]:
    clean = [dict(item) for item in sources]
    return {
        "state": "SUPPORTED" if clean else "INSUFFICIENT",
        "sources": clean,
        "rationale": [rationale],
    }


def build_portfolio_fit_evidence(
    fund16: Mapping[str, Any],
    fund17: Mapping[str, Any],
    *,
    candidate_exposures: Mapping[str, Mapping[str, Any]] | None = None,
    portfolio_exposure: Mapping[str, Any] | None = None,
    portfolio_weights: Mapping[str, float] | None = None,
    generated_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build exact FUND18 evidence rows for every FUND17 candidate.

    This builder records facts only. It deliberately does not derive
    STRONG/PARTIAL/WEAK or LOW/MEDIUM/HIGH portfolio-fit assessments.
    """

    fund16_rows = _candidate_rows(fund16)
    fund17_codes = _fund17_codes(fund17)

    if set(fund16_rows) != set(fund17_codes):
        raise PortfolioFitEvidenceBuilderError(
            "fund16_fund17_candidate_set_mismatch"
        )

    as_of = generated_at or _iso_now()
    context = fund17.get("portfolio_context")
    if not isinstance(context, Mapping):
        raise PortfolioFitEvidenceBuilderError("portfolio_context_invalid")

    if context.get("human_supplied") is not True:
        raise PortfolioFitEvidenceBuilderError("portfolio_context_not_human_supplied")
    if context.get("research_only") is not True:
        raise PortfolioFitEvidenceBuilderError("portfolio_context_not_research_only")
    if context.get("execution_authority") is not False:
        raise PortfolioFitEvidenceBuilderError("portfolio_context_execution_authority")

    desired_roles = tuple(str(x) for x in context.get("desired_roles") or ())
    existing_exposures = tuple(
        str(x) for x in context.get("existing_exposures") or ()
    )
    constraints = tuple(str(x) for x in context.get("constraints") or ())

    exposures = candidate_exposures or {}
    weights = portfolio_weights or {}

    result: dict[str, dict[str, Any]] = {}

    for code in fund17_codes:
        research = fund16_rows[code]
        category = str(research.get("category") or "").strip()

        role_sources = [
            _source(
                source_type="FUND17_PORTFOLIO_CONTEXT",
                source_id="fund17:portfolio_context",
                observed_fact=(
                    "Human-approved desired portfolio roles: "
                    + ", ".join(desired_roles)
                ),
                as_of=as_of,
            ),
            _source(
                source_type="FUND16_CANDIDATE_RESEARCH",
                source_id=f"fund16:{code}",
                observed_fact=f"{code} research category is {category}.",
                as_of=as_of,
            ),
        ]

        exposure_sources: list[dict[str, Any]] = []
        candidate_exposure = exposures.get(code)
        if isinstance(candidate_exposure, Mapping):
            primary = str(
                candidate_exposure.get("primary_exposure") or ""
            ).strip()
            exposure_as_of = _normalize_source_as_of(
                candidate_exposure.get("as_of"),
                as_of,
            )
            if primary:
                exposure_sources.append(
                    _source(
                        source_type="KAP_OFFICIAL",
                        source_id=f"kap-economic-exposure:{code}",
                        observed_fact=(
                            f"{code} official primary economic exposure "
                            f"is {primary}."
                        ),
                        as_of=exposure_as_of,
                        claim={
                            "field": "economic_exposure",
                            "value": primary,
                        },
                    )
                )

        portfolio_sources: list[dict[str, Any]] = []
        if isinstance(portfolio_exposure, Mapping):
            completeness = str(
                portfolio_exposure.get("completeness") or ""
            ).strip()
            buckets = portfolio_exposure.get("buckets")

            observable_buckets: list[str] = []
            if isinstance(buckets, Sequence) and not isinstance(
                buckets, (str, bytes)
            ):
                for bucket in buckets:
                    if not isinstance(bucket, Mapping):
                        continue
                    bucket_id = str(bucket.get("bucket_id") or "").strip()
                    weight = bucket.get("observable_weight_pct")
                    if not bucket_id or weight is None:
                        continue
                    observable_buckets.append(
                        f"{bucket_id}={float(weight):.4f}%"
                    )

            if completeness and observable_buckets:
                portfolio_sources.append(
                    _source(
                        source_type="PORTFOLIO_CANONICAL",
                        source_id="portfolio-economic-exposure",
                        observed_fact=(
                            "Canonical observable portfolio economic exposure: "
                            + ", ".join(observable_buckets)
                            + f"; completeness={completeness}."
                        ),
                        as_of=as_of,
                    )
                )

        concentration_sources: list[dict[str, Any]] = []
        if code in weights:
            weight = float(weights[code])
            concentration_sources.append(
                _source(
                    source_type="PORTFOLIO_CANONICAL",
                    source_id=f"portfolio-weight:{code}",
                    observed_fact=(
                        f"{code} observable current portfolio weight is "
                        f"{weight:.4f}%."
                    ),
                    as_of=as_of,
                    claim={
                        "field": "portfolio_weight",
                        "value": weight,
                        "unit": "percent",
                    },
                )
            )

        common_overlap_sources = (
            exposure_sources + portfolio_sources
            if exposure_sources and portfolio_sources
            else []
        )

        evidence = {
            "schema_version": EVIDENCE_SCHEMA,
            "fund_code": code,
            "research_only": True,
            "execution_authority": False,
            "production_persist": False,
            "dimensions": {
                "role_fit": _dimension(
                    role_sources,
                    rationale=(
                        "Candidate research category and human-approved "
                        "portfolio roles recorded; no fit assessment derived."
                    ),
                ),
                "economic_overlap": _dimension(
                    common_overlap_sources,
                    rationale=(
                        "Candidate and portfolio exposure facts recorded when "
                        "available; no overlap threshold applied."
                    ),
                ),
                "diversification_contribution": _dimension(
                    common_overlap_sources,
                    rationale=(
                        "Exposure facts recorded when available; no "
                        "diversification assessment derived."
                    ),
                ),
                "concentration_risk": _dimension(
                    concentration_sources,
                    rationale=(
                        "Observable current candidate weight recorded when "
                        "available; no concentration threshold applied."
                    ),
                ),
            },
        }

        # Contract validation is part of the production builder boundary.
        result[code] = normalize_candidate_evidence(
            evidence,
            expected_code=code,
            not_after=as_of,
        )

    return result
