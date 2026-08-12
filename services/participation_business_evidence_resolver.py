from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional, Tuple

from services.participation_business_contract import BusinessActivityEvidence


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_source_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build_business_activity_evidence_from_candidate(
    candidate: Mapping[str, Any],
) -> BusinessActivityEvidence:
    symbol = _normalize_symbol(candidate.get("symbol"))
    company_name = _optional_text(candidate.get("company_name"))
    sector_theme = _optional_text(candidate.get("sector_theme"))
    industry = _optional_text(candidate.get("industry"))
    notes = _optional_text(candidate.get("notes"))
    sic_code = _optional_text(candidate.get("sic_code") or candidate.get("sic"))
    sic_description = _optional_text(candidate.get("sic_description"))

    evidence_refs: list[tuple[str, str]] = []
    warnings: list[str] = []

    if sector_theme:
        evidence_refs.append(("sector_theme", sector_theme))
    if industry:
        evidence_refs.append(("industry", industry))
    if notes:
        evidence_refs.append(("notes", "candidate.notes"))
    if sic_code:
        evidence_refs.append(("sic_code", sic_code))

    sector = sector_theme
    if industry and sector_theme and industry.lower() != sector_theme.lower():
        warnings.append(
            "Both sector_theme and industry present; sector_theme used as structured sector evidence."
        )
    elif industry and not sector_theme:
        sector = industry
        warnings.append(
            "Industry used as structured sector evidence; separate sector field unavailable."
        )
    elif sector_theme and not industry:
        warnings.append(
            "Structured industry not persisted separately; sector_theme used as sector evidence."
        )

    if sic_code is None:
        warnings.append("SIC code not available on candidate record.")

    source = "candidate_record"
    if candidate.get("data_source"):
        source = f"candidate_record:{candidate.get('data_source')}"

    return BusinessActivityEvidence(
        symbol=symbol,
        company_name=company_name,
        sector=sector,
        industry=industry if industry and industry != sector else None,
        sic_code=sic_code,
        sic_description=sic_description,
        business_description=notes,
        revenue_segments=(),
        source=source,
        source_date=_parse_source_date(candidate.get("source_updated_at")),
        evidence_refs=tuple(evidence_refs),
        warnings=tuple(dict.fromkeys(warnings)),
    )
