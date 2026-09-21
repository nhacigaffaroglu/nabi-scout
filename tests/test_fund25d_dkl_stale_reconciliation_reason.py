from types import SimpleNamespace

from services.turkiye_fund_scanner import (
    supersede_cached_pdr_reconciliation_reasons,
)


def _pdr(reconciled):
    return SimpleNamespace(
        weights=SimpleNamespace(
            weight_reconciled=reconciled,
        )
    )


def test_missing_current_pdr_supersedes_cached_reconciliation_when_holdings_missing():
    result = supersede_cached_pdr_reconciliation_reasons(
        (
            "PDR_RECONCILIATION_FAILED",
            "HOLDINGS_MISSING",
            "EVIDENCE_STALE",
        ),
        None,
    )

    assert result == [
        "HOLDINGS_MISSING",
        "EVIDENCE_STALE",
    ]


def test_missing_current_pdr_preserves_cached_reconciliation_without_missing_holdings():
    result = supersede_cached_pdr_reconciliation_reasons(
        (
            "PDR_RECONCILIATION_FAILED",
            "EVIDENCE_STALE",
        ),
        None,
    )

    assert result == [
        "PDR_RECONCILIATION_FAILED",
        "EVIDENCE_STALE",
    ]


def test_current_unreconciled_pdr_preserves_reconciliation_blocker():
    result = supersede_cached_pdr_reconciliation_reasons(
        (
            "PDR_RECONCILIATION_FAILED",
            "HOLDINGS_MISSING",
        ),
        _pdr(False),
    )

    assert result == [
        "PDR_RECONCILIATION_FAILED",
        "HOLDINGS_MISSING",
    ]


def test_current_reconciled_pdr_supersedes_cached_reconciliation_blocker():
    result = supersede_cached_pdr_reconciliation_reasons(
        (
            "PDR_RECONCILIATION_FAILED",
            "PARTICIPATION_REVIEW",
        ),
        _pdr(True),
    )

    assert result == [
        "PARTICIPATION_REVIEW",
    ]
