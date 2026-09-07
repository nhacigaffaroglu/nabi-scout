from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from services.candidate_contract import CandidateRecord, CandidateSourceTrace
from services.candidate_eligibility import (
    CandidateEligibilityInput,
    evaluate_candidate_eligibility,
)

NO_FI_EVALUATION_VERSION = "NO_FI_EVALUATION"
STATE_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _float_equal(left: Any, right: Any, *, tolerance: float = 1e-9) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= tolerance


def _stable_scanner_payload(row: Any) -> dict[str, Any]:
    return {
        "fund_code": _symbol(getattr(row, "fund_code", "")),
        "scanner_status": getattr(row, "scanner_status", None),
        "participation": getattr(row, "participation", None),
        "research_allowed": bool(getattr(row, "research_allowed", False)),
        "fi_profile": getattr(row, "fi_profile", None),
        "fi_score": getattr(row, "fi_score", None),
        "fi_state": getattr(row, "fi_state", None),
        "confidence": getattr(row, "confidence", None),
        "data_completeness": getattr(row, "data_completeness", None),
        "exposure": getattr(row, "exposure", None),
        "missing_evidence": list(getattr(row, "missing_evidence", ()) or ()),
    }


def _stable_fi_payload(view: Any) -> Optional[dict[str, Any]]:
    if view is None:
        return None
    return {
        "symbol": _symbol(getattr(view, "symbol", "")),
        "fund_type_profile": getattr(view, "fund_type_profile", None),
        "state": getattr(view, "state", None),
        "score": getattr(view, "score", None),
        "confidence": getattr(view, "confidence", None),
        "as_of": getattr(view, "as_of", None),
        "facts_version": getattr(view, "facts_version", None),
        "engine_version": getattr(view, "engine_version", None),
        "provenance": list(getattr(view, "provenance", ()) or ()),
        "missing_evidence": list(getattr(view, "missing_evidence", ()) or ()),
        "publishable": bool(getattr(view, "publishable", False)),
        "completeness": getattr(view, "completeness", None),
    }


def fund_candidate_snapshot_id(
    scanner_row: Any,
    intelligence: Any,
    *,
    scanner_as_of: str,
) -> str:
    payload = {
        "scanner_as_of": scanner_as_of,
        "scanner": _stable_scanner_payload(scanner_row),
        "fund_intelligence": _stable_fi_payload(intelligence),
    }
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "fund-candidate-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def _assert_scanner_fi_consistency(scanner_row: Any, view: Any) -> None:
    if view is None:
        return

    code = _symbol(getattr(scanner_row, "fund_code", ""))
    view_symbol = _symbol(getattr(view, "symbol", ""))
    if code != view_symbol:
        raise ValueError(f"fund_candidate_symbol_mismatch:{code}:{view_symbol}")

    checks = (
        ("score", getattr(scanner_row, "fi_score", None), getattr(view, "score", None)),
        ("confidence", getattr(scanner_row, "confidence", None), getattr(view, "confidence", None)),
        (
            "completeness",
            getattr(scanner_row, "data_completeness", None),
            getattr(view, "completeness", None),
        ),
    )
    for field, scanner_value, fi_value in checks:
        if not _float_equal(scanner_value, fi_value):
            raise ValueError(
                f"fund_candidate_{field}_mismatch:{code}:{scanner_value}:{fi_value}"
            )

    scanner_state = getattr(scanner_row, "fi_state", None)
    fi_state = getattr(view, "state", None)
    if scanner_state != fi_state:
        raise ValueError(
            f"fund_candidate_state_mismatch:{code}:{scanner_state}:{fi_state}"
        )

    scanner_profile = getattr(scanner_row, "fi_profile", None)
    fi_profile = getattr(view, "fund_type_profile", None)
    if scanner_profile != fi_profile:
        raise ValueError(
            f"fund_candidate_profile_mismatch:{code}:{scanner_profile}:{fi_profile}"
        )


def _dimension_scores(view: Any) -> tuple[tuple[str, float], ...]:
    if view is None:
        return ()
    rows = []
    for dimension in tuple(getattr(view, "dimensions", ()) or ()):
        score = getattr(dimension, "score", None)
        if score is None:
            continue
        rows.append((str(getattr(dimension, "name", "")), float(score)))
    return tuple(rows)


def candidate_from_turkiye_fund(
    scanner_row: Any,
    intelligence: Any,
    *,
    scanner_as_of: str,
) -> CandidateRecord:
    code = _symbol(getattr(scanner_row, "fund_code", ""))
    if not code:
        raise ValueError("fund_candidate_fund_code_required")
    if not scanner_as_of:
        raise ValueError("fund_candidate_scanner_as_of_required")

    _assert_scanner_fi_consistency(scanner_row, intelligence)

    snapshot_id = fund_candidate_snapshot_id(
        scanner_row,
        intelligence,
        scanner_as_of=scanner_as_of,
    )

    missing = tuple(getattr(scanner_row, "missing_evidence", ()) or ())
    required_evidence_fresh = not any(
        item in {"SOURCE_STALE", "EVIDENCE_STALE"}
        for item in missing
    )

    eligibility = evaluate_candidate_eligibility(
        CandidateEligibilityInput(
            scanner_status=str(getattr(scanner_row, "scanner_status", "") or ""),
            participation_status=getattr(scanner_row, "participation", None),
            research_allowed=bool(getattr(scanner_row, "research_allowed", False)),
            intelligence_publishable=bool(
                getattr(intelligence, "publishable", False)
                if intelligence is not None
                else False
            ),
            economic_exposure_known=bool(getattr(scanner_row, "exposure", None)),
            analysis_snapshot_id=snapshot_id,
            missing_evidence=missing,
            required_evidence_fresh=required_evidence_fresh,
        )
    )

    state = (
        getattr(intelligence, "state", None)
        if intelligence is not None
        else getattr(scanner_row, "fi_state", None)
    ) or STATE_INSUFFICIENT_DATA
    score = (
        getattr(intelligence, "score", None)
        if intelligence is not None
        else getattr(scanner_row, "fi_score", None)
    )
    confidence = (
        getattr(intelligence, "confidence", None)
        if intelligence is not None
        else getattr(scanner_row, "confidence", None)
    )
    completeness = (
        getattr(intelligence, "completeness", None)
        if intelligence is not None
        else getattr(scanner_row, "data_completeness", None)
    )
    engine_version = (
        str(getattr(intelligence, "engine_version", "") or "")
        if intelligence is not None
        else NO_FI_EVALUATION_VERSION
    )
    facts_version = (
        str(getattr(intelligence, "facts_version", "") or "") or None
        if intelligence is not None
        else None
    )
    analysis_as_of = (
        getattr(intelligence, "as_of", None)
        if intelligence is not None
        else None
    ) or scanner_as_of
    provenance = (
        tuple(getattr(intelligence, "provenance", ()) or ())
        if intelligence is not None
        else ()
    )

    return CandidateRecord(
        symbol=code,
        market="TR",
        instrument_type="FUND",
        total_score=float(score) if score is not None else None,
        confidence=float(confidence) if confidence is not None else 0.0,
        intelligence_state=str(state),
        eligibility=eligibility,
        source_trace=CandidateSourceTrace(
            analysis_snapshot_id=snapshot_id,
            analysis_as_of=analysis_as_of,
            score_version=engine_version or NO_FI_EVALUATION_VERSION,
            facts_version=facts_version,
            source_provenance=provenance,
        ),
        recommendation_band=None,
        data_completeness=(
            float(completeness) if completeness is not None else None
        ),
        economic_exposure=getattr(scanner_row, "exposure", None),
        peer_group=getattr(scanner_row, "fi_profile", None),
        sub_scores=_dimension_scores(intelligence),
        limitations=(
            "RESEARCH_ONLY",
            "NO_8E_AUTHORITY",
            "NO_NEW_MONEY_AUTHORITY",
            "NO_TRADE_AUTHORITY",
            "NO_PORTFOLIO_WRITE_AUTHORITY",
        ),
    )


def candidates_from_turkiye_fund_scanner(
    scanner_result: Any,
    intelligence_by_symbol: Mapping[str, Any],
) -> tuple[CandidateRecord, ...]:
    known_codes = {
        _symbol(getattr(row, "fund_code", ""))
        for row in tuple(getattr(scanner_result, "rows", ()) or ())
    }
    extras = sorted(
        _symbol(code)
        for code in intelligence_by_symbol
        if _symbol(code) not in known_codes
    )
    if extras:
        raise ValueError(
            "fund_candidate_unknown_intelligence_symbols:" + ",".join(extras)
        )

    as_of = str(getattr(scanner_result, "as_of", "") or "")
    return tuple(
        candidate_from_turkiye_fund(
            row,
            intelligence_by_symbol.get(_symbol(getattr(row, "fund_code", ""))),
            scanner_as_of=as_of,
        )
        for row in tuple(getattr(scanner_result, "rows", ()) or ())
    )
