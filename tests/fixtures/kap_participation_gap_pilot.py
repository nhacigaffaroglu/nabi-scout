"""Captured KAP excerpts for Participation financial-gap tests."""

from __future__ import annotations

from tests.fixtures.kap_public_pilot import compact_public_html


FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public KAP excerpt for Participation gap regression. "
    "Not a Participation verdict."
)

# Raw thousands, matching public KAP 2026-06-30 pages.
PILOT_CURRENT_RECEIVABLES = {
    "ASELS": "47.167.326",
    "BIMAS": "42.525.418",
    "TUPRS": "78.747.644",
}
PILOT_NONCURRENT_RECEIVABLES = {
    "ASELS": "82.608.746",
}


def ytd_receivable_html(
    *,
    current: str = "47.167.326",
    noncurrent: str = "82.608.746",
    borrowings: str = "8.586.218",
) -> str:
    return compact_public_html(
        current_receivables=current,
        noncurrent_receivables=noncurrent,
        longterm_borrowings=borrowings,
    )


def fy_with_receivables_html(*, current: str = "40.000.000") -> str:
    return compact_public_html(
        bs_current="Cari Dönem<br>31.12.2025",
        bs_prior="Önceki Dönem<br>31.12.2024",
        is_current="Cari Dönem 01.01.2025 - 31.12.2025",
        is_prior="Önceki Dönem 01.01.2024 - 31.12.2024",
        include_quarter=False,
        cash="34.251.653",
        assets="508.228.606",
        revenue="120.000.000",
        profit="12.000.000",
        current_receivables=current,
    )
