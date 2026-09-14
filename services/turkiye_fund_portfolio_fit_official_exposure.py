"""Production-safe official exposure adapter for FUND18.

Reuses the canonical TEFAS/KAP provider and official Türkiye fund economic
classification. It performs no persistence, portfolio mutation, ranking,
recommendation, allocation, or execution.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Sequence

from services.official_tefas_product import default_tefas_fund_provider


class PortfolioFitOfficialExposureError(ValueError):
    """Fail-closed FUND18 official-exposure adapter error."""


def _plain(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return dict(asdict(value))
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise PortfolioFitOfficialExposureError(
        f"unsupported_classification_type:{type(value).__name__}"
    )


def load_official_candidate_exposures(
    fund_codes: Sequence[str],
    *,
    evidence_packs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return canonical official economic-exposure facts for FUND18 candidates.

    Missing, unsupported, unready, or failed classifications are omitted so
    the downstream FUND18 evidence builder remains fail-closed.
    """

    codes = tuple(
        dict.fromkeys(
            str(code).strip().upper()
            for code in fund_codes
            if str(code).strip()
        )
    )

    if not codes:
        return {}

    if evidence_packs is None:
        raise PortfolioFitOfficialExposureError(
            "current_evidence_packs_required"
        )

    packs = dict(evidence_packs)
    provider = default_tefas_fund_provider(evidence_packs=packs)

    result: dict[str, dict[str, Any]] = {}

    for code in codes:
        if not provider.supports(code):
            continue

        try:
            classification = provider.economic_classification(code)
        except (ValueError, RuntimeError):
            continue

        if classification is None:
            continue

        row = _plain(classification)

        if row.get("ready") is not True:
            continue
        if str(row.get("source") or "") != "kap_fund":
            continue
        if not str(row.get("primary_exposure") or "").strip():
            continue
        if not str(row.get("as_of") or "").strip():
            continue

        result[code] = row

    return result
