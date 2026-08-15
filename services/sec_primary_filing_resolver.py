from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence


_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
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
