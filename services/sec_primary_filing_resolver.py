from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence


_ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "40-F"})
_REJECT_FORMS = frozenset({"10-Q", "10-Q/A", "8-K"})


@dataclass(frozen=True)
class SECPrimaryFilingRef:
    cik: str
    form: str
    fiscal_year: Optional[int]
    filing_date: str
    accession_number: str
    primary_document: str
    filing_url: str
    retrieved_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_cik(cik: int | str) -> str:
    text = str(cik).strip().lstrip("0") or "0"
    return text


def _accession_path(accession: str) -> str:
    return str(accession or "").replace("-", "")


def build_filing_url(*, cik: int | str, accession: str, primary_document: str) -> str:
    cik_text = _normalize_cik(cik)
    accession_path = _accession_path(accession)
    document = str(primary_document or "").strip()
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_text}/"
        f"{accession_path}/{document}"
    )


def _parse_fiscal_year(report_date: Optional[str], filing_date: str) -> Optional[int]:
    for candidate in (report_date, filing_date):
        if not candidate:
            continue
        try:
            return int(str(candidate)[:4])
        except ValueError:
            continue
    return None


def _iter_recent_filings(submissions: Mapping[str, Any]) -> Sequence[Dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent") or {}
    forms = recent.get("form") or []
    if not forms:
        return ()
    keys = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "primaryDocument",
        "form",
    )
    rows: list[Dict[str, Any]] = []
    for index in range(len(forms)):
        row = {key: (recent.get(key) or [None] * len(forms))[index] for key in keys}
        rows.append(row)
    return rows


def resolve_latest_annual_filing(
    submissions: Mapping[str, Any],
    *,
    cik: int | str,
    forms: Optional[Sequence[str]] = None,
) -> Optional[SECPrimaryFilingRef]:
    allowed_forms = frozenset(forms or _ANNUAL_FORMS)
    candidates: list[Dict[str, Any]] = []
    for row in _iter_recent_filings(submissions):
        form = str(row.get("form") or "").strip()
        if form in _REJECT_FORMS:
            continue
        if form not in allowed_forms:
            continue
        accession = str(row.get("accessionNumber") or "").strip()
        primary_document = str(row.get("primaryDocument") or "").strip()
        filing_date = str(row.get("filingDate") or "").strip()
        if not accession or not primary_document or not filing_date:
            continue
        candidates.append(row)

    if not candidates:
        return None

    candidates.sort(key=lambda row: str(row.get("filingDate") or ""), reverse=True)
    selected = candidates[0]
    form = str(selected.get("form") or "10-K")
    accession = str(selected.get("accessionNumber") or "")
    primary_document = str(selected.get("primaryDocument") or "")
    filing_date = str(selected.get("filingDate") or "")
    report_date = str(selected.get("reportDate") or "") or None
    cik_text = _normalize_cik(cik)
    return SECPrimaryFilingRef(
        cik=cik_text,
        form=form,
        fiscal_year=_parse_fiscal_year(report_date, filing_date),
        filing_date=filing_date,
        accession_number=accession,
        primary_document=primary_document,
        filing_url=build_filing_url(
            cik=cik_text,
            accession=accession,
            primary_document=primary_document,
        ),
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )


def resolve_annual_filing_for_period(
    submissions: Mapping[str, Any],
    *,
    cik: int | str,
    preferred_period_end: Optional[str] = None,
    preferred_accession: Optional[str] = None,
) -> Optional[SECPrimaryFilingRef]:
    """Prefer the annual filing whose report date or accession matches the
    canonical financial period. Does not invent a filing when none exist.
    """
    latest = resolve_latest_annual_filing(submissions, cik=cik)
    if latest is None:
        return None
    preferred_end = str(preferred_period_end or "").strip()[:10]
    preferred_accn = str(preferred_accession or "").strip()
    if not preferred_end and not preferred_accn:
        return latest

    allowed_forms = _ANNUAL_FORMS
    matches: list[Dict[str, Any]] = []
    for row in _iter_recent_filings(submissions):
        form = str(row.get("form") or "").strip()
        if form not in allowed_forms:
            continue
        accession = str(row.get("accessionNumber") or "").strip()
        report_date = str(row.get("reportDate") or "").strip()[:10]
        if preferred_accn and accession == preferred_accn:
            matches.append(row)
            continue
        if preferred_end and report_date == preferred_end:
            matches.append(row)
    if not matches:
        return latest
    matches.sort(key=lambda row: str(row.get("filingDate") or ""), reverse=True)
    selected = matches[0]
    cik_text = _normalize_cik(cik)
    accession = str(selected.get("accessionNumber") or "")
    primary_document = str(selected.get("primaryDocument") or "")
    filing_date = str(selected.get("filingDate") or "")
    return SECPrimaryFilingRef(
        cik=cik_text,
        form=str(selected.get("form") or "10-K"),
        fiscal_year=_parse_fiscal_year(
            str(selected.get("reportDate") or "") or None,
            filing_date,
        ),
        filing_date=filing_date,
        accession_number=accession,
        primary_document=primary_document,
        filing_url=build_filing_url(
            cik=cik_text,
            accession=accession,
            primary_document=primary_document,
        ),
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
