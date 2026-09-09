"""Read-only Türkiye fund candidate detail view model.

D1 Product / Decision Layer foundation.

This module:
- consumes an existing TurkiyeFundScannerResult.to_dict() payload,
- applies the same four candidate eligibility gates used by FUND14B,
- derives deterministic candidate rank with the FUND14B tie-break contract,
- exposes research context for UI rendering.

It does not:
- change Participation or FI methodology,
- propose/lock thresholds or recommendation bands,
- call 8E or New Money,
- place trades/orders,
- write portfolio or production state,
- perform network access.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Mapping

from services.turkiye_fund_candidate_artifact import (
    PARTICIPATION_UYGUN,
    RANK_TIE_BREAK,
    READY,
)

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")

EXCLUSION_SCANNER_NOT_READY = "SCANNER_NOT_READY"
EXCLUSION_PARTICIPATION_NOT_UYGUN = "PARTICIPATION_NOT_UYGUN"
EXCLUSION_RESEARCH_NOT_ALLOWED = "RESEARCH_NOT_ALLOWED"
EXCLUSION_FI_SCORE_NOT_PUBLISHABLE = "FI_SCORE_NOT_PUBLISHABLE"

CANDIDATE_DETAIL_SCHEMA = "turkiye_fund_candidate_detail_1"


class CandidateDetailContractError(ValueError):
    """Fail-closed candidate detail input contract violation."""


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _metric_for_sort(value: Any) -> float:
    number = _finite_number(value)
    return number if number is not None else -1.0


def validate_fund_code(value: Any) -> str:
    if not isinstance(value, str):
        raise CandidateDetailContractError("fund_code_must_be_string")
    code = value.strip()
    # Validation only: no silent uppercasing/autocorrect.
    if code != value or code != code.upper() or not _CODE_RE.fullmatch(code):
        raise CandidateDetailContractError(f"fund_code_not_canonical:{value!r}")
    return code


def candidate_exclusion_reasons(row: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    if row.get("scanner_status") != READY:
        reasons.append(EXCLUSION_SCANNER_NOT_READY)
    if row.get("participation") != PARTICIPATION_UYGUN:
        reasons.append(EXCLUSION_PARTICIPATION_NOT_UYGUN)
    if row.get("research_allowed") is not True:
        reasons.append(EXCLUSION_RESEARCH_NOT_ALLOWED)
    if _finite_number(row.get("fi_score")) is None:
        reasons.append(EXCLUSION_FI_SCORE_NOT_PUBLISHABLE)
    return tuple(reasons)


def _rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_metric_for_sort(row.get("fi_score")),
        -_metric_for_sort(row.get("data_completeness")),
        -_metric_for_sort(row.get("confidence")),
        str(row["fund_code"]),
    )


@dataclass(frozen=True)
class CandidateGateView:
    gate: str
    passed: bool
    observed: Any
    required: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TurkiyeFundCandidateDetail:
    schema_version: str
    fund_code: str
    fund_name: str | None
    founder: str | None
    category: str | None
    candidate_eligible: bool
    candidate_rank: int | None
    candidate_count: int
    exclusion_reasons: tuple[str, ...]
    fi_score: float | None
    fi_state: str | None
    fi_profile: str | None
    peer_view: str | None
    scanner_status: str | None
    participation: str | None
    research_allowed: bool
    exposure: str | None
    confidence: float | None
    data_completeness: float | None
    return_1y: float | None
    max_drawdown: float | None
    reason: str | None
    missing_evidence: tuple[str, ...]
    universe_states: tuple[str, ...]
    scanner_rank: int | None
    as_of: str | None
    calculated_at: str | None
    rank_contract: tuple[str, ...]
    identity: dict[str, Any] | None
    gates: tuple[CandidateGateView, ...]
    research_only: bool = True
    threshold_proposed: bool = False
    threshold_locked: bool = False
    recommendation_band_applied: bool = False
    execution_authority: bool = False
    production_persist: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gates"] = [gate.to_dict() for gate in self.gates]
        return payload


def _identity_map(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    identities = payload.get("identities") or []
    if not isinstance(identities, list):
        raise CandidateDetailContractError("identities_must_be_list")
    out: dict[str, dict[str, Any]] = {}
    for raw in identities:
        if not isinstance(raw, Mapping):
            raise CandidateDetailContractError("identity_must_be_object")
        code = validate_fund_code(raw.get("fund_code"))
        if code in out:
            raise CandidateDetailContractError(f"duplicate_identity:{code}")
        out[code] = dict(raw)
    return out


def build_candidate_detail_catalog(
    scanner_payload: Mapping[str, Any],
) -> dict[str, TurkiyeFundCandidateDetail]:
    payload = dict(scanner_payload)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise CandidateDetailContractError("rows_must_be_list")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise CandidateDetailContractError("scanner_row_must_be_object")
        row = dict(raw)
        code = validate_fund_code(row.get("fund_code"))
        if code in seen:
            raise CandidateDetailContractError(f"duplicate_fund_code:{code}")
        seen.add(code)
        row["fund_code"] = code
        normalized.append(row)

    eligible = [row for row in normalized if not candidate_exclusion_reasons(row)]
    eligible.sort(key=_rank_key)
    rank_map = {row["fund_code"]: index for index, row in enumerate(eligible, start=1)}
    identities = _identity_map(payload)

    out: dict[str, TurkiyeFundCandidateDetail] = {}
    for row in normalized:
        code = row["fund_code"]
        exclusions = candidate_exclusion_reasons(row)
        fi_score = _finite_number(row.get("fi_score"))
        confidence = _finite_number(row.get("confidence"))
        completeness = _finite_number(row.get("data_completeness"))
        return_1y = _finite_number(row.get("return_1y"))
        max_drawdown = _finite_number(row.get("max_drawdown"))

        gates = (
            CandidateGateView(
                gate="SCANNER_READY",
                passed=row.get("scanner_status") == READY,
                observed=row.get("scanner_status"),
                required=READY,
            ),
            CandidateGateView(
                gate="PARTICIPATION_UYGUN",
                passed=row.get("participation") == PARTICIPATION_UYGUN,
                observed=row.get("participation"),
                required=PARTICIPATION_UYGUN,
            ),
            CandidateGateView(
                gate="RESEARCH_ALLOWED",
                passed=row.get("research_allowed") is True,
                observed=row.get("research_allowed"),
                required="True",
            ),
            CandidateGateView(
                gate="FI_SCORE_PUBLISHABLE",
                passed=fi_score is not None,
                observed=row.get("fi_score"),
                required="finite numeric FI score",
            ),
        )

        out[code] = TurkiyeFundCandidateDetail(
            schema_version=CANDIDATE_DETAIL_SCHEMA,
            fund_code=code,
            fund_name=row.get("fund_name"),
            founder=row.get("founder"),
            category=row.get("category"),
            candidate_eligible=not exclusions,
            candidate_rank=rank_map.get(code),
            candidate_count=len(eligible),
            exclusion_reasons=exclusions,
            fi_score=fi_score,
            fi_state=row.get("fi_state"),
            fi_profile=row.get("fi_profile"),
            peer_view=row.get("peer_view"),
            scanner_status=row.get("scanner_status"),
            participation=row.get("participation"),
            research_allowed=row.get("research_allowed") is True,
            exposure=row.get("exposure"),
            confidence=confidence,
            data_completeness=completeness,
            return_1y=return_1y,
            max_drawdown=max_drawdown,
            reason=row.get("reason"),
            missing_evidence=tuple(row.get("missing_evidence") or ()),
            universe_states=tuple(row.get("universe_states") or ()),
            scanner_rank=row.get("rank"),
            as_of=payload.get("as_of"),
            calculated_at=payload.get("calculated_at"),
            rank_contract=tuple(RANK_TIE_BREAK),
            identity=identities.get(code),
            gates=gates,
        )

    return out


def build_candidate_detail(
    scanner_payload: Mapping[str, Any],
    fund_code: str,
) -> TurkiyeFundCandidateDetail:
    code = validate_fund_code(fund_code)
    catalog = build_candidate_detail_catalog(scanner_payload)
    try:
        return catalog[code]
    except KeyError as exc:
        raise CandidateDetailContractError(f"fund_not_in_scanner:{code}") from exc
