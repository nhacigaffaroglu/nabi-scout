from __future__ import annotations

from services.turkiye_fund_review_reason_presentation import (
    UNCLASSIFIED_REVIEW_GATE,
    actionable_reason_depth,
    extract_review_reasons,
    parse_reason_text,
    primary_review_reason,
)


def test_parses_holding_group_suffix_without_creating_fake_reason_tokens():
    row = {
        "scanner_status": "REVIEW_REQUIRED",
        "reason": (
            "Review required: PARTICIPATION_REVIEW,MATERIAL_CONTRADICTION,"
            "HOLDING_GROUP_OUTSIDE_MANDATE:CASH,LEASE_CERTIFICATE,OTHER,"
            "PARTICIPATION_ACCOUNT,REPO,FI_INSUFFICIENT_DATA"
        ),
        "missing_evidence": ("PARTICIPATION_REVIEW", "FI_INSUFFICIENT_DATA"),
    }

    reasons = extract_review_reasons(row)

    assert "HOLDING_GROUP_OUTSIDE_MANDATE:CASH" in reasons
    assert "HOLDING_GROUP_OUTSIDE_MANDATE:LEASE_CERTIFICATE" in reasons
    assert "HOLDING_GROUP_OUTSIDE_MANDATE:OTHER" in reasons
    assert "HOLDING_GROUP_OUTSIDE_MANDATE:PARTICIPATION_ACCOUNT" in reasons
    assert "HOLDING_GROUP_OUTSIDE_MANDATE:REPO" in reasons
    assert "CASH" not in reasons
    assert "OTHER" not in reasons
    assert "REPO" not in reasons


def test_detailed_reason_text_is_combined_with_canonical_missing_evidence():
    row = {
        "scanner_status": "REVIEW_REQUIRED",
        "reason": "Review required: PDR_WEIGHTS_UNRECONCILED,ECONOMIC_EXPOSURE_UNKNOWN",
        "missing_evidence": ("PDR_RECONCILIATION_FAILED", "FI_INSUFFICIENT_DATA"),
    }

    reasons = extract_review_reasons(row)

    assert reasons == (
        "PDR_WEIGHTS_UNRECONCILED",
        "ECONOMIC_EXPOSURE_UNKNOWN",
        "PDR_RECONCILIATION_FAILED",
        "FI_INSUFFICIENT_DATA",
    )


def test_primary_reason_prefers_actionable_root_cause_over_wrapper_reasons():
    row = {
        "scanner_status": "REVIEW_REQUIRED",
        "reason": (
            "Review required: PARTICIPATION_REVIEW,GOVERNANCE_NOT_CONFIRMED,"
            "FI_INSUFFICIENT_DATA,FI_NOT_PUBLISHABLE"
        ),
        "missing_evidence": (
            "PARTICIPATION_REVIEW",
            "GOVERNANCE_EVIDENCE_MISSING",
            "FI_INSUFFICIENT_DATA",
        ),
    }

    primary = primary_review_reason(row)

    assert primary is not None
    assert primary.family == "GOVERNANCE"
    assert primary.code in {"GOVERNANCE_NOT_CONFIRMED", "GOVERNANCE_EVIDENCE_MISSING"}
    assert actionable_reason_depth(row) == 2


def test_pdr_source_problem_precedes_downstream_exposure_problem():
    row = {
        "scanner_status": "REVIEW_REQUIRED",
        "reason": (
            "Review required: PDR_RECONCILIATION_FAILED,PARTICIPATION_REVIEW,"
            "PDR_WEIGHTS_UNRECONCILED,ECONOMIC_EXPOSURE_UNKNOWN,FI_INSUFFICIENT_DATA"
        ),
        "missing_evidence": (
            "PDR_RECONCILIATION_FAILED",
            "PARTICIPATION_REVIEW",
            "ECONOMIC_EXPOSURE_UNKNOWN",
            "FI_INSUFFICIENT_DATA",
        ),
    }

    primary = primary_review_reason(row)

    assert primary is not None
    assert primary.family == "PDR_RECONCILIATION"


def test_empty_non_ready_row_gets_diagnostic_fallback_without_policy_change():
    row = {
        "scanner_status": "REVIEW_REQUIRED",
        "reason": "",
        "missing_evidence": (),
    }

    assert extract_review_reasons(row) == (UNCLASSIFIED_REVIEW_GATE,)
    assert primary_review_reason(row).code == UNCLASSIFIED_REVIEW_GATE


def test_ready_row_with_empty_reasons_stays_empty():
    row = {"scanner_status": "READY", "reason": "", "missing_evidence": ()}

    assert extract_review_reasons(row) == ()
    assert primary_review_reason(row) is None


def test_parse_reason_text_ignores_unrecognised_free_text():
    assert parse_reason_text("READY: canonical FI score") == ()
