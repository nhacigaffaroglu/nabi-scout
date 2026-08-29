"""Local SEC submissions fixtures for 8-K signal tests and UAT.

These are constructed submissions-shaped payloads. They are not written
to production signal tables.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def submissions_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    cik: str = "1108524",
    name: str = "SALESFORCE, INC.",
) -> dict[str, Any]:
    keys = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "primaryDocument",
        "form",
        "items",
    )
    recent = {key: [row.get(key) for row in rows] for key in keys}
    return {
        "cik": str(cik).zfill(10),
        "name": name,
        "tickers": ["CRM"],
        "filings": {"recent": recent},
    }


def fixture_crm_single_item_8k() -> dict[str, Any]:
    return submissions_from_rows(
        [
            {
                "accessionNumber": "0001108524-26-000088",
                "filingDate": "2026-03-15",
                "reportDate": "2026-03-15",
                "acceptanceDateTime": "2026-03-15T21:15:00.000Z",
                "primaryDocument": "crm-8k.htm",
                "form": "8-K",
                "items": "2.02,9.01",
            },
            {
                "accessionNumber": "0001108524-25-000010",
                "filingDate": "2025-01-02",
                "reportDate": "2025-01-02",
                "acceptanceDateTime": "2025-01-02T16:00:00.000Z",
                "primaryDocument": "crm-8k-old.htm",
                "form": "8-K",
                "items": "8.01",
            },
            {
                "accessionNumber": "0001108524-26-000050",
                "filingDate": "2026-02-01",
                "reportDate": "2026-01-31",
                "acceptanceDateTime": "2026-02-01T21:00:00.000Z",
                "primaryDocument": "crm-10k.htm",
                "form": "10-K",
                "items": "",
            },
        ]
    )


def fixture_crm_multi_item_8k() -> dict[str, Any]:
    return submissions_from_rows(
        [
            {
                "accessionNumber": "0001108524-26-000200",
                "filingDate": "2026-07-01",
                "reportDate": "2026-07-01",
                "acceptanceDateTime": "2026-07-01T21:30:00.000Z",
                "primaryDocument": "crm-8k-multi.htm",
                "form": "8-K",
                "items": "2.02,5.02,9.01",
            }
        ]
    )


def fixture_crm_unknown_items_8k() -> dict[str, Any]:
    return submissions_from_rows(
        [
            {
                "accessionNumber": "0001108524-26-000300",
                "filingDate": "2026-08-01",
                "reportDate": "2026-08-01",
                "acceptanceDateTime": "2026-08-01T18:00:00.000Z",
                "primaryDocument": "crm-8k-other.htm",
                "form": "8-K",
                "items": "Results of operations, other events",
            }
        ]
    )


def fixture_submissions_by_symbol(
    *,
    include_multi: bool = True,
    extra: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, dict[str, Any]]:
    payload = dict(extra or {})
    payload["CRM"] = (
        fixture_crm_multi_item_8k() if include_multi else fixture_crm_single_item_8k()
    )
    return payload
