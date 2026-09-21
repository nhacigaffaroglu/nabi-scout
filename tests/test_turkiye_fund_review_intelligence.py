from __future__ import annotations

from services.turkiye_fund_review_intelligence import (
    SCHEMA_VERSION,
    build_review_intelligence,
)


def scanner_payload():
    return {
        "rows": [
            {
                "fund_code": "AAA",
                "fund_name": "AAA FONU",
                "scanner_status": "READY",
                "participation": "Uygun",
                "fi_profile": "SUKUK_PARTICIPATION_FUND",
                "reason": "READY: canonical FI score",
                "missing_evidence": (),
            },
            {
                "fund_code": "BBB",
                "fund_name": "BBB FONU",
                "scanner_status": "REVIEW_REQUIRED",
                "participation": "Kontrol Et",
                "fi_profile": "SUKUK_PARTICIPATION_FUND",
                "reason": (
                    "Review required: PDR_RECONCILIATION_FAILED,PARTICIPATION_REVIEW,"
                    "PDR_WEIGHTS_UNRECONCILED,ECONOMIC_EXPOSURE_UNKNOWN,"
                    "FI_INSUFFICIENT_DATA"
                ),
                "missing_evidence": (
                    "PDR_RECONCILIATION_FAILED",
                    "PARTICIPATION_REVIEW",
                    "ECONOMIC_EXPOSURE_UNKNOWN",
                    "FI_INSUFFICIENT_DATA",
                ),
            },
            {
                "fund_code": "CCC",
                "fund_name": "CCC FONU",
                "scanner_status": "REVIEW_REQUIRED",
                "participation": "Kontrol Et",
                "fi_profile": "EQUITY_PARTICIPATION_FUND",
                "reason": (
                    "Review required: PARTICIPATION_REVIEW,GOVERNANCE_NOT_CONFIRMED,"
                    "FI_INSUFFICIENT_DATA"
                ),
                "missing_evidence": (
                    "PARTICIPATION_REVIEW",
                    "GOVERNANCE_EVIDENCE_MISSING",
                    "FI_INSUFFICIENT_DATA",
                ),
            },
            {
                "fund_code": "DDD",
                "fund_name": "DDD FONU",
                "scanner_status": "BLOCKED",
                "participation": None,
                "fi_profile": None,
                "reason": "",
                "missing_evidence": (),
            },
        ]
    }


def test_builds_read_only_review_intelligence_contract():
    result = build_review_intelligence(scanner_payload())

    assert result.schema_version == SCHEMA_VERSION
    assert result.execution_authority is False
    assert result.production_persist is False
    assert result.status_counts == {
        "BLOCKED": 1,
        "READY": 1,
        "REVIEW_REQUIRED": 2,
    }
    assert len(result.fund_diagnostics) == 3


def test_primary_root_causes_are_operational_not_generic_wrappers():
    result = build_review_intelligence(scanner_payload())
    by_code = {row.fund_code: row for row in result.fund_diagnostics}

    assert by_code["BBB"].primary_family == "PDR_RECONCILIATION"
    assert by_code["CCC"].primary_family == "GOVERNANCE"
    assert by_code["DDD"].primary_root_cause == "UNCLASSIFIED_REVIEW_GATE"


def test_counts_and_profile_breakdown_are_deterministic():
    result = build_review_intelligence(scanner_payload())

    assert result.root_cause_counts["PDR_RECONCILIATION_FAILED"] == 1
    assert result.unclassified_count == 1
    assert (
        result.profile_reason_counts["SUKUK_PARTICIPATION_FUND"][
            "PDR_RECONCILIATION_FAILED"
        ]
        == 1
    )
    assert result.reason_depth_counts


def test_to_dict_contains_expected_read_model_fields_only_as_diagnostics():
    payload = build_review_intelligence(scanner_payload()).to_dict()

    for key in (
        "status_counts",
        "reason_counts",
        "root_cause_counts",
        "reason_depth_counts",
        "profile_reason_counts",
        "fund_diagnostics",
        "unclassified_count",
    ):
        assert key in payload

    assert payload["execution_authority"] is False
    assert payload["production_persist"] is False
