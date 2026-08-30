"""TEST-ONLY synthetic KAP raw lines.

These are not official ASELS, BIMAS, or TUPRS financials.
They exist only to validate the BIST-1B pipeline.
"""

from __future__ import annotations

from typing import Optional

from services.kap_financial_contract import (
    ACCOUNT_CASH,
    ACCOUNT_CURRENT_ASSETS,
    ACCOUNT_CURRENT_LIABILITIES,
    ACCOUNT_NET_INCOME,
    ACCOUNT_OPERATING_INCOME,
    ACCOUNT_REVENUE,
    ACCOUNT_TOTAL_ASSETS,
    ACCOUNT_TOTAL_DEBT,
    ACCOUNT_TOTAL_EQUITY,
    CONSOLIDATION_CONSOLIDATED,
    KAP_SOURCE,
    KapRawFinancialLine,
    NATURE_FLOW,
    NATURE_POINT_IN_TIME,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_YTD,
    SCALE_MILLION,
    SCALE_THOUSAND,
    STATEMENT_BALANCE,
    STATEMENT_INCOME,
)

FIXTURE_DISCLAIMER = (
    "TEST-ONLY synthetic KAP raw lines. Not official ASELS/BIMAS/TUPRS financials."
)


def _line(
    symbol: str,
    account_code: str,
    raw_value,
    *,
    statement: str,
    nature: str,
    period: str = PERIOD_FY,
    unit_scale: Optional[int] = SCALE_MILLION,
    unit_label: str = "MILLION TRY",
    currency: str = "TRY",
    period_end: str = "2024-12-31",
    account_label: str = "",
    **overrides,
) -> KapRawFinancialLine:
    payload = dict(
        symbol=symbol,
        issuer_id=f"TEST-{symbol}",
        statement_type=statement,
        period_start="2024-01-01" if nature == NATURE_FLOW else None,
        period_end=period_end,
        reporting_period=period,
        fact_nature=nature,
        consolidation=CONSOLIDATION_CONSOLIDATED,
        currency=currency,
        unit_scale=unit_scale,
        unit_label=unit_label,
        account_code=account_code,
        account_label=account_label or account_code,
        raw_value=raw_value,
        source=KAP_SOURCE,
        source_document_id=f"TEST-DOC-{symbol}",
        published_at="2025-02-15",
        as_of=period_end,
        provenance={"fixture": True, "disclaimer": FIXTURE_DISCLAIMER},
    )
    payload.update(overrides)
    return KapRawFinancialLine(**payload)


def asels_raw_lines() -> tuple[KapRawFinancialLine, ...]:
    return (
        _line("ASELS", ACCOUNT_REVENUE, 120.0, statement=STATEMENT_INCOME, nature=NATURE_FLOW),
        _line("ASELS", ACCOUNT_OPERATING_INCOME, 18.0, statement=STATEMENT_INCOME, nature=NATURE_FLOW),
        _line("ASELS", ACCOUNT_NET_INCOME, 12.0, statement=STATEMENT_INCOME, nature=NATURE_FLOW),
        _line("ASELS", ACCOUNT_TOTAL_ASSETS, 400.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("ASELS", ACCOUNT_TOTAL_EQUITY, 220.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("ASELS", ACCOUNT_CASH, 40.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("ASELS", ACCOUNT_TOTAL_DEBT, 80.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("ASELS", ACCOUNT_CURRENT_ASSETS, 150.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("ASELS", ACCOUNT_CURRENT_LIABILITIES, 75.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line(
            "ASELS",
            "NABI_TEST.UNKNOWN.WIDGETS",
            9.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            account_label="Widgets",
        ),
    )


def bimas_raw_lines() -> tuple[KapRawFinancialLine, ...]:
    return (
        _line(
            "BIMAS",
            ACCOUNT_REVENUE,
            900.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_NET_INCOME,
            45.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_TOTAL_ASSETS,
            3_000.0,
            statement=STATEMENT_BALANCE,
            nature=NATURE_POINT_IN_TIME,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_TOTAL_EQUITY,
            1_200.0,
            statement=STATEMENT_BALANCE,
            nature=NATURE_POINT_IN_TIME,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_CASH,
            300.0,
            statement=STATEMENT_BALANCE,
            nature=NATURE_POINT_IN_TIME,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_TOTAL_DEBT,
            600.0,
            statement=STATEMENT_BALANCE,
            nature=NATURE_POINT_IN_TIME,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_REVENUE,
            210.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            period=PERIOD_YTD,
            period_end="2025-06-30",
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
        _line(
            "BIMAS",
            ACCOUNT_OPERATING_INCOME,
            None,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            unit_scale=SCALE_THOUSAND,
            unit_label="THOUSAND TRY",
        ),
    )


def tuprs_raw_lines() -> tuple[KapRawFinancialLine, ...]:
    return (
        _line("TUPRS", ACCOUNT_TOTAL_ASSETS, 500.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("TUPRS", ACCOUNT_TOTAL_EQUITY, 200.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("TUPRS", ACCOUNT_CASH, 25.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line("TUPRS", ACCOUNT_TOTAL_DEBT, 100.0, statement=STATEMENT_BALANCE, nature=NATURE_POINT_IN_TIME),
        _line(
            "TUPRS",
            ACCOUNT_NET_INCOME,
            30.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            period=PERIOD_Q,
            period_start="2024-10-01",
            period_end="2024-12-31",
        ),
        _line(
            "TUPRS",
            ACCOUNT_REVENUE,
            80.0,
            statement=STATEMENT_INCOME,
            nature=NATURE_FLOW,
            period=PERIOD_Q,
            period_start="2024-10-01",
            period_end="2024-12-31",
        ),
    )


PILOT_RAW_LINES = {
    "ASELS": asels_raw_lines,
    "BIMAS": bimas_raw_lines,
    "TUPRS": tuprs_raw_lines,
}
