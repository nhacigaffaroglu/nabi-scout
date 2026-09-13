from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from services.security_intelligence_authority_parity import (
    LIVE_SI_ROLE,
    PERSISTED_SI_DECISION_AUTHORITY,
    SecurityIntelligenceParityStatus,
    compare_security_intelligence_authority,
)
from services.security_intelligence_contract import (
    DIM_BALANCE_SHEET,
    DIM_DATA_QUALITY,
    DIM_GROWTH,
    DIM_MOMENTUM,
    DIM_PROFITABILITY,
    DIM_QUALITY,
    DIM_RISK,
    DIM_VALUATION,
    DimensionResult,
    SecurityIntelligenceView,
)
from services.security_intelligence_snapshot_service import (
    snapshot_from_row,
    snapshot_row_from_view,
    summarise_security_intelligence_data_quality,
)


def _dimension(
    name: str,
    *,
    score: float = 70.0,
    status: str = "STRONG",
    confidence: float = 0.8,
    reason_codes: tuple[str, ...] = (),
) -> DimensionResult:
    return DimensionResult(
        name=name,
        score=score,
        status=status,
        confidence=confidence,
        facts_used=(),
        missing_facts=(),
        reason_codes=reason_codes,
    )


def _view(
    *,
    overall_score: float = 72.0,
    investment_state: str = "ATTRACTIVE",
    overall_confidence: float = 0.82,
    data_quality_status: str = "STRONG",
    data_quality_reason_codes: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
) -> SecurityIntelligenceView:
    return SecurityIntelligenceView(
        symbol="CRM",
        quality=_dimension(DIM_QUALITY),
        growth=_dimension(DIM_GROWTH),
        profitability=_dimension(DIM_PROFITABILITY),
        balance_sheet=_dimension(DIM_BALANCE_SHEET),
        valuation=_dimension(DIM_VALUATION),
        momentum=_dimension(DIM_MOMENTUM),
        risk=_dimension(DIM_RISK),
        data_quality=_dimension(
            DIM_DATA_QUALITY,
            status=data_quality_status,
            reason_codes=data_quality_reason_codes,
        ),
        overall_score=overall_score,
        overall_status="STRONG",
        overall_confidence=overall_confidence,
        strengths=("QUALITY",),
        weaknesses=(),
        risk_flags=risk_flags,
        change_flags=(),
        participation_status="UYGUN",
        research_allowed=True,
        investment_state=investment_state,
        investable=True,
    )


def _persisted(view: SecurityIntelligenceView, **updates):
    row = snapshot_row_from_view(view, as_of="2026-09-12")
    row.update(updates)
    return snapshot_from_row(row)


def test_match_uses_persisted_snapshot_as_authority() -> None:
    view = _view()
    result = compare_security_intelligence_authority(view, _persisted(view))

    assert result.authority == PERSISTED_SI_DECISION_AUTHORITY
    assert result.live_role == LIVE_SI_ROLE
    assert result.status == SecurityIntelligenceParityStatus.MATCH
    assert result.mismatched_fields == ()


def test_numeric_parity_normalizes_decimal_and_float_values() -> None:
    view = _view(
        overall_score=72.1234564,
        overall_confidence=0.82000004,
    )
    persisted = replace(
        _persisted(view),
        overall_score=Decimal("72.12345639"),
        overall_confidence=Decimal("0.820000039"),
    )

    result = compare_security_intelligence_authority(view, persisted)

    assert result.status == SecurityIntelligenceParityStatus.MATCH
    assert result.mismatched_fields == ()


def test_persisted_missing_does_not_promote_live_view_to_authority() -> None:
    result = compare_security_intelligence_authority(_view(), None)

    assert result.status == SecurityIntelligenceParityStatus.PERSISTED_MISSING
    assert result.authority == PERSISTED_SI_DECISION_AUTHORITY
    assert result.live_role == LIVE_SI_ROLE
    assert result.persisted is None
    assert result.mismatched_fields == ()


def test_mismatch_reports_only_decision_meaning_fields() -> None:
    view = _view()
    persisted = _persisted(
        view,
        overall_score=61.0,
        investment_state="WATCH",
        overall_confidence=0.55,
        data_quality={"status": "WEAK"},
    )

    result = compare_security_intelligence_authority(view, persisted)

    assert result.status == SecurityIntelligenceParityStatus.MISMATCH
    assert result.mismatched_fields == (
        "overall_score",
        "investment_state",
        "overall_confidence",
        "data_quality",
    )


def test_metadata_only_differences_do_not_create_mismatch() -> None:
    view = _view()
    base = _persisted(view)
    persisted = replace(
        base,
        as_of="2024-01-01",
        engine_version="older-engine",
        facts_version="older-facts",
        dimension_scores={"QUALITY": 1.0},
        dimension_statuses={"QUALITY": "WEAK"},
        reason_codes=("NON_AUTHORITY_NOTE",),
        risk_flags=("NON_STALE_RISK",),
    )

    result = compare_security_intelligence_authority(view, persisted)

    assert result.status == SecurityIntelligenceParityStatus.MATCH
    assert result.mismatched_fields == ()


def test_existing_stale_marker_changes_effective_authority_projection() -> None:
    view = _view()
    persisted = replace(_persisted(view), risk_flags=("STALE_DATA",))

    result = compare_security_intelligence_authority(view, persisted)

    assert result.status == SecurityIntelligenceParityStatus.MISMATCH
    assert result.mismatched_fields == ("stale",)
    assert result.live.stale is False
    assert result.persisted is not None
    assert result.persisted.stale is True


def test_data_quality_summary_matches_8e_priority_rule() -> None:
    assert summarise_security_intelligence_data_quality(None) is None
    assert summarise_security_intelligence_data_quality({}) is None
    assert (
        summarise_security_intelligence_data_quality(
            {"overall": "OK", "freshness_status": "FRESH", "status": "GOOD"}
        )
        == "GOOD"
    )
    assert (
        summarise_security_intelligence_data_quality(
            {"overall": "OK", "freshness_status": "FRESH"}
        )
        == "FRESH"
    )
    assert summarise_security_intelligence_data_quality({"overall": "OK"}) == "OK"
    assert summarise_security_intelligence_data_quality({"other": "IGNORED"}) is None
