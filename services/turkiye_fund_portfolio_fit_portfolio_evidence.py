"""Canonical portfolio-fact adapter for FUND18.

Converts an already-built PortfolioIntelligenceView into factual portfolio
evidence inputs for the FUND18 evidence builder.

This adapter:
- reuses canonical portfolio economic exposure,
- records current candidate portfolio weights,
- performs no portfolio-fit assessment,
- applies no concentration threshold,
- performs no ranking/recommendation/allocation,
- performs no persistence or execution.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from services.portfolio_economic_exposure import build_economic_exposure
from services.wealth_exposure_bridge import build_wealth_exposure_context


class PortfolioFitPortfolioEvidenceError(ValueError):
    """Fail-closed canonical portfolio-evidence adapter error."""


def _plain(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        row = to_dict()
        if isinstance(row, Mapping):
            return dict(row)

    raise PortfolioFitPortfolioEvidenceError(
        f"unsupported_portfolio_exposure_type:{type(value).__name__}"
    )


def build_canonical_portfolio_fit_inputs(
    portfolio_view: Any,
    fund_codes: Sequence[str],
) -> dict[str, Any]:
    """Return canonical portfolio facts consumed by FUND18 evidence builder.

    Candidate weight semantics are explicit:

    - held candidate + canonical numeric current weight -> that weight;
    - candidate not held in the canonical portfolio -> 0.0%;
    - ambiguous/unavailable holding context -> omit the weight and let FUND18
      fail closed for concentration evidence.

    No LOW/MEDIUM/HIGH assessment is produced here.
    """

    if portfolio_view is None:
        raise PortfolioFitPortfolioEvidenceError(
            "canonical_portfolio_view_required"
        )

    codes = tuple(
        dict.fromkeys(
            str(code).strip().upper()
            for code in fund_codes
            if str(code).strip()
        )
    )

    exposure = _plain(build_economic_exposure(portfolio_view))

    completeness = str(exposure.get("completeness") or "").strip()
    buckets = exposure.get("buckets")

    if not completeness:
        raise PortfolioFitPortfolioEvidenceError(
            "portfolio_exposure_completeness_missing"
        )

    if not isinstance(buckets, list):
        raise PortfolioFitPortfolioEvidenceError(
            "portfolio_exposure_buckets_invalid"
        )

    weights: dict[str, float] = {}

    for code in codes:
        try:
            context = build_wealth_exposure_context(
                portfolio_view,
                code,
            )
        except (TypeError, ValueError, RuntimeError):
            continue

        if context is None:
            continue

        row = _plain(context)

        held = row.get("held")
        weight = row.get("current_weight_pct")

        if held is False:
            # Canonical portfolio explicitly says the candidate is not held.
            weights[code] = 0.0
            continue

        if held is True and isinstance(weight, (int, float)) and not isinstance(
            weight, bool
        ):
            weights[code] = float(weight)

    return {
        "portfolio_exposure": exposure,
        "portfolio_weights": weights,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
    }
