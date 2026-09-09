"""FUND14B candidate artifact core.

Pure research transformation:
FUND14A research snapshot -> deterministic candidate artifact.

This module does not:
- change Participation methodology,
- invent or lock FI/candidate thresholds,
- call 8E or New Money,
- place trades/orders,
- write portfolio state,
- perform network access,
- persist production state.

Promotion in this module means downstream *research-candidate promotion only*.
It never grants execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping, Sequence

INPUT_SCHEMA = "fund14a_research_snapshot_3"
OUTPUT_SCHEMA = "fund14b_candidate_artifact_4"
DEFAULT_EXPECTED_SOURCE_HEAD = "c97e629f4e7a74a9e7a3879c6878e87eee9977f1"

READY = "READY"
PARTICIPATION_UYGUN = "Uygun"
RANK_TIE_BREAK = (
    "fi_score_desc",
    "data_completeness_desc",
    "confidence_desc",
    "fund_code_asc",
)

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")


class CandidateArtifactContractError(ValueError):
    """Fail-closed input/policy contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateArtifactContractError(f"{field}_must_be_object")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CandidateArtifactContractError(f"{field}_must_be_list")
    return value


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _metric_for_sort(value: Any) -> float:
    number = _finite_number(value)
    return number if number is not None else -1.0


def _validated_code(value: Any) -> str:
    if not isinstance(value, str):
        raise CandidateArtifactContractError("fund_code_must_be_string")
    code = value.strip()
    # Validation only. Do not silently uppercase/autocorrect upstream symbols.
    if code != value or code != code.upper() or not _CODE_RE.fullmatch(code):
        raise CandidateArtifactContractError(f"fund_code_not_canonical:{value!r}")
    return code


def _assert_research_firewall(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("research_only") is not True:
        raise CandidateArtifactContractError("upstream_research_only_not_true")

    proof = _as_dict(snapshot.get("write_proof"), field="write_proof")
    if proof.get("persist") not in (False, None):
        raise CandidateArtifactContractError("upstream_persist_not_false")
    writes = proof.get("production_writes")
    if writes not in (None, [], ()):
        raise CandidateArtifactContractError("upstream_production_writes_nonzero")

    for key in ("eight_e_calls", "new_money_calls", "trades", "portfolio_writes"):
        value = proof.get(key, 0)
        if isinstance(value, bool) or value not in (0, 0.0, None):
            raise CandidateArtifactContractError(f"upstream_{key}_nonzero")


def _assert_baseline_delta_shape(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    delta = _as_dict(
        snapshot.get("participation_baseline_delta"),
        field="participation_baseline_delta",
    )
    added = delta.get("added")
    removed = delta.get("removed")
    if not isinstance(added, list) or not isinstance(removed, list):
        raise CandidateArtifactContractError("participation_baseline_delta_lists_invalid")
    if any(not isinstance(x, str) for x in added + removed):
        raise CandidateArtifactContractError("participation_baseline_delta_code_invalid")
    manual = delta.get("manual_review_required")
    if not isinstance(manual, bool):
        raise CandidateArtifactContractError(
            "participation_baseline_delta_manual_review_invalid"
        )
    return delta


def _row_exclusion_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("scanner_status") != READY:
        reasons.append("SCANNER_NOT_READY")
    if row.get("participation") != PARTICIPATION_UYGUN:
        reasons.append("PARTICIPATION_NOT_UYGUN")
    if row.get("research_allowed") is not True:
        reasons.append("RESEARCH_NOT_ALLOWED")
    if _finite_number(row.get("fi_score")) is None:
        reasons.append("FI_SCORE_NOT_PUBLISHABLE")
    return reasons


def _rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_metric_for_sort(row.get("fi_score")),
        -_metric_for_sort(row.get("data_completeness")),
        -_metric_for_sort(row.get("confidence")),
        str(row["fund_code"]),
    )


def _candidate_view(row: Mapping[str, Any], *, candidate_rank: int) -> dict[str, Any]:
    keep = (
        "fund_code",
        "fund_name",
        "category",
        "rank",
        "fi_score",
        "fi_state",
        "confidence",
        "participation",
        "research_allowed",
        "exposure",
        "return_1y",
        "max_drawdown",
        "data_completeness",
        "scanner_status",
        "universe_states",
        "reason",
        "missing_evidence",
        "fi_profile",
        "peer_view",
        "founder",
    )
    out = {key: row.get(key) for key in keep}
    out["candidate_rank"] = candidate_rank
    out["upstream_scanner_rank"] = out.pop("rank", None)
    return out


def _exclusion_view(row: Mapping[str, Any], reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "fund_code": row["fund_code"],
        "scanner_status": row.get("scanner_status"),
        "participation": row.get("participation"),
        "research_allowed": row.get("research_allowed"),
        "fi_score": row.get("fi_score"),
        "exclusion_reasons": list(reasons),
    }


def _validate_threshold_policy(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    if policy is None:
        return {
            "locked": False,
            "fi_min": None,
            "source": None,
            "decision_id": None,
        }

    p = dict(policy)
    locked = p.get("locked")
    if not isinstance(locked, bool):
        raise CandidateArtifactContractError("threshold_policy_locked_must_be_bool")

    if not locked:
        if p.get("fi_min") is not None:
            raise CandidateArtifactContractError(
                "unlocked_threshold_must_not_have_fi_min"
            )
        return {
            "locked": False,
            "fi_min": None,
            "source": p.get("source"),
            "decision_id": p.get("decision_id"),
        }

    fi_min = _finite_number(p.get("fi_min"))
    if fi_min is None:
        raise CandidateArtifactContractError("locked_threshold_fi_min_required")
    if not 0.0 <= fi_min <= 100.0:
        raise CandidateArtifactContractError("locked_threshold_fi_min_out_of_range")
    source = p.get("source")
    decision_id = p.get("decision_id")
    if not isinstance(source, str) or not source.strip():
        raise CandidateArtifactContractError("locked_threshold_source_required")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise CandidateArtifactContractError("locked_threshold_decision_id_required")
    return {
        "locked": True,
        "fi_min": fi_min,
        "source": source.strip(),
        "decision_id": decision_id.strip(),
    }


def build_candidate_artifact(
    research_snapshot: Mapping[str, Any],
    *,
    threshold_policy: Mapping[str, Any] | None = None,
    expected_source_head: str | None = DEFAULT_EXPECTED_SOURCE_HEAD,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a research-only candidate artifact from one FUND14A snapshot.

    Threshold behavior is deliberately fail-closed:
    - no policy -> unlocked -> no promotions;
    - unlocked policy cannot carry a numeric threshold;
    - locked policy requires explicit source + decision_id + numeric fi_min;
    - even a locked threshold cannot promote when upstream activation is unsafe
      or Participation baseline delta requires review.
    """
    snapshot = _as_dict(research_snapshot, field="research_snapshot")

    if snapshot.get("schema_version") != INPUT_SCHEMA:
        raise CandidateArtifactContractError("unsupported_fund14a_schema")

    source_head = snapshot.get("source_head")
    if not isinstance(source_head, str) or not source_head:
        raise CandidateArtifactContractError("source_head_missing")
    if expected_source_head is not None and source_head != expected_source_head:
        raise CandidateArtifactContractError(
            f"source_head_mismatch:{source_head}"
        )

    _assert_research_firewall(snapshot)
    delta = _assert_baseline_delta_shape(snapshot)

    scanner = _as_dict(snapshot.get("scanner"), field="scanner")
    raw_rows = _as_list(scanner.get("rows"), field="scanner.rows")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        row = _as_dict(raw, field="scanner.row")
        code = _validated_code(row.get("fund_code"))
        if code in seen:
            raise CandidateArtifactContractError(f"duplicate_fund_code:{code}")
        seen.add(code)
        row["fund_code"] = code
        rows.append(row)

    eligible_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    exclusion_counts: dict[str, int] = {}

    for row in rows:
        reasons = _row_exclusion_reasons(row)
        if not reasons:
            eligible_rows.append(row)
            continue
        excluded.append(_exclusion_view(row, reasons))
        for reason in reasons:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1

    eligible_rows.sort(key=_rank_key)
    candidates = [
        _candidate_view(row, candidate_rank=index)
        for index, row in enumerate(eligible_rows, start=1)
    ]
    excluded.sort(key=lambda row: row["fund_code"])

    policy = _validate_threshold_policy(threshold_policy)
    activation_safe = snapshot.get("activation_safe") is True
    baseline_clean = (
        not delta["added"]
        and not delta["removed"]
        and delta["manual_review_required"] is False
    )

    gate_reasons: list[str] = []
    if not activation_safe:
        gate_reasons.append("UPSTREAM_ACTIVATION_UNSAFE")
    if not baseline_clean:
        gate_reasons.append("PARTICIPATION_BASELINE_REVIEW_REQUIRED")
    if not policy["locked"]:
        gate_reasons.append("THRESHOLD_UNLOCKED")

    promotion_gate_open = not gate_reasons
    promotion_eligible = []
    if promotion_gate_open:
        threshold = float(policy["fi_min"])
        promotion_eligible = [
            {
                "fund_code": row["fund_code"],
                "candidate_rank": row["candidate_rank"],
                "fi_score": row["fi_score"],
            }
            for row in candidates
            if float(row["fi_score"]) >= threshold
        ]

    timestamp = generated_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source": {
            "fund14a_schema_version": snapshot["schema_version"],
            "source_head": source_head,
            "as_of": snapshot.get("as_of"),
            "calculated_at": snapshot.get("calculated_at"),
        },
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "methodology_ownership": {
            "participation": False,
            "fund_intelligence": False,
            "eight_e": False,
            "new_money": False,
            "portfolio_allocation": False,
        },
        "rank_contract": list(RANK_TIE_BREAK),
        "candidate_contract": {
            "required_scanner_status": READY,
            "required_participation": PARTICIPATION_UYGUN,
            "required_research_allowed": True,
            "requires_numeric_fi_score": True,
        },
        "counts": {
            "scanner_rows": len(rows),
            "eligible_candidates": len(candidates),
            "excluded_rows": len(excluded),
            "promotion_eligible": len(promotion_eligible),
        },
        "candidates": candidates,
        "excluded": excluded,
        "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
        "threshold_policy": policy,
        "promotion_gate": {
            "open": promotion_gate_open,
            "reasons": gate_reasons,
            "meaning": "research_candidate_promotion_only",
            "execution_authority": False,
        },
        "promotion_eligible": promotion_eligible,
        "upstream_activation": {
            "activation_safe": activation_safe,
            "participation_baseline_delta": delta,
        },
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
        "limitations": [
            "Research candidate ranking is not a buy/sell instruction.",
            "This core does not own Participation methodology.",
            "This core does not own FI scoring methodology.",
            "No threshold is proposed or locked by default.",
            "No 8E, New Money, trade, order, or portfolio execution authority exists.",
        ],
    }
