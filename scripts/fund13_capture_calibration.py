#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

SOURCE_SCHEMA = "fund14b_candidate_artifact_4"
SNAPSHOT_VERSION = "fund13_calibration_snapshot_3"
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"FAIL {field} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise SystemExit(f"FAIL {field} must be finite")
    return out


def fingerprint(rows: list[dict[str, Any]]) -> str:
    body = json.dumps(
        sorted(rows, key=lambda x: x["fund_code"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _assert_write_firewall(artifact: dict[str, Any]) -> None:
    if artifact.get("research_only") is not True:
        raise SystemExit("FAIL artifact research_only")
    if artifact.get("execution_authority") is not False:
        raise SystemExit("FAIL execution authority")
    if artifact.get("production_persist") is not False:
        raise SystemExit("FAIL production persist")

    proof = artifact.get("write_proof")
    if not isinstance(proof, dict):
        raise SystemExit("FAIL write_proof")
    expected = {
        "production_writes": 0,
        "trade_actions": 0,
        "orders": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
    }
    if proof != expected:
        raise SystemExit(f"FAIL write firewall mismatch: {proof!r}")


def load_artifact(path: Path) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise SystemExit(f"FAIL missing FUND14B artifact: {path}")
    raw = path.read_bytes()
    artifact = json.loads(raw.decode("utf-8"))

    if artifact.get("schema_version") != SOURCE_SCHEMA:
        raise SystemExit("FAIL FUND14B artifact schema")
    _assert_write_firewall(artifact)

    source = artifact.get("source")
    if not isinstance(source, dict):
        raise SystemExit("FAIL source object")
    if source.get("fund14a_schema_version") != "fund14a_research_snapshot_3":
        raise SystemExit("FAIL FUND14A source schema")
    if not isinstance(source.get("source_head"), str) or not source.get("source_head"):
        raise SystemExit("FAIL source_head")
    if not isinstance(source.get("as_of"), str) or not source.get("as_of"):
        raise SystemExit("FAIL as_of")

    policy = artifact.get("threshold_policy")
    if not isinstance(policy, dict):
        raise SystemExit("FAIL threshold policy object")
    if policy.get("locked") is not False or policy.get("fi_min") is not None:
        raise SystemExit("FAIL threshold already locked/proposed")

    gate = artifact.get("promotion_gate")
    if not isinstance(gate, dict):
        raise SystemExit("FAIL promotion gate object")
    if gate.get("open") is not False:
        raise SystemExit("FAIL promotion gate open")
    if gate.get("reasons") != ["THRESHOLD_UNLOCKED"]:
        raise SystemExit(f"FAIL unexpected promotion gate reasons: {gate.get('reasons')!r}")
    if gate.get("execution_authority") is not False:
        raise SystemExit("FAIL promotion execution authority")
    if artifact.get("promotion_eligible") != []:
        raise SystemExit("FAIL promotion_eligible must be empty")

    upstream = artifact.get("upstream_activation")
    if not isinstance(upstream, dict) or upstream.get("activation_safe") is not True:
        raise SystemExit("FAIL upstream activation unsafe")
    delta = upstream.get("participation_baseline_delta")
    if not isinstance(delta, dict):
        raise SystemExit("FAIL Participation delta")
    if delta.get("added") != [] or delta.get("removed") != []:
        raise SystemExit("FAIL Participation baseline delta")
    if delta.get("manual_review_required") is not False:
        raise SystemExit("FAIL Participation manual review required")

    counts = artifact.get("counts")
    if not isinstance(counts, dict):
        raise SystemExit("FAIL counts object")
    candidates = artifact.get("candidates")
    if not isinstance(candidates, list):
        raise SystemExit("FAIL candidates list")
    if counts.get("eligible_candidates") != len(candidates):
        raise SystemExit("FAIL candidate count mismatch")
    if counts.get("promotion_eligible") != 0:
        raise SystemExit("FAIL promotion count nonzero")

    return artifact, raw


def normalize_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = artifact["candidates"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    profile_seen: dict[str, int] = {}

    for expected_rank, row in enumerate(raw_rows, start=1):
        if not isinstance(row, dict):
            raise SystemExit("FAIL candidate row object")
        code = row.get("fund_code")
        if not isinstance(code, str) or code != code.strip() or code != code.upper():
            raise SystemExit(f"FAIL noncanonical fund_code: {code!r}")
        if not _CODE_RE.fullmatch(code):
            raise SystemExit(f"FAIL invalid fund_code: {code!r}")
        if code in seen:
            raise SystemExit(f"FAIL duplicate candidate: {code}")
        seen.add(code)

        if row.get("candidate_rank") != expected_rank:
            raise SystemExit(
                f"FAIL non-contiguous candidate rank: {code}:{row.get('candidate_rank')}"
            )
        if row.get("scanner_status") != "READY":
            raise SystemExit(f"FAIL non-READY candidate: {code}")
        if row.get("participation") != "Uygun":
            raise SystemExit(f"FAIL Participation candidate: {code}")
        if row.get("research_allowed") is not True:
            raise SystemExit(f"FAIL research disallowed candidate: {code}")
        if "recommendation_band" in row:
            raise SystemExit(f"FAIL recommendation band present: {code}")

        score = _finite_number(row.get("fi_score"), field=f"{code}.fi_score")
        confidence = row.get("confidence")
        completeness = row.get("data_completeness")
        if confidence is not None:
            confidence = _finite_number(confidence, field=f"{code}.confidence")
        if completeness is not None:
            completeness = _finite_number(completeness, field=f"{code}.data_completeness")

        profile = str(row.get("fi_profile") or "NONE")
        profile_seen[profile] = profile_seen.get(profile, 0) + 1

        rows.append({
            "fund_code": code,
            "rank": expected_rank,
            "profile_rank": profile_seen[profile],
            "fi_score": score,
            "fi_state": row.get("fi_state"),
            "fi_profile": profile,
            "peer_view": row.get("peer_view"),
            "confidence": confidence,
            "data_completeness": completeness,
            "exposure": row.get("exposure"),
            "upstream_scanner_rank": row.get("upstream_scanner_rank"),
        })

    return rows


def build_snapshot(artifact: dict[str, Any], raw: bytes) -> dict[str, Any]:
    rows = normalize_rows(artifact)
    source = artifact["source"]
    rank_contract = artifact.get("rank_contract")
    if rank_contract != [
        "fi_score_desc",
        "data_completeness_desc",
        "confidence_desc",
        "fund_code_asc",
    ]:
        raise SystemExit(f"FAIL rank contract: {rank_contract!r}")

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source": "FUND14B_CANDIDATE_ARTIFACT_V4",
        "source_schema_version": artifact["schema_version"],
        "source_head": source["source_head"],
        "as_of": source["as_of"],
        "source_generated_at": artifact.get("generated_at"),
        "source_artifact_sha256": _sha256_bytes(raw),
        "rank_contract": list(rank_contract),
        "thresholds_proposed": False,
        "thresholds_locked": False,
        "band_policy_applied": False,
        "eligible_scored_count": len(rows),
        "eligible_set": sorted(row["fund_code"] for row in rows),
        "candidate_set_fingerprint": fingerprint(
            [{"fund_code": r["fund_code"], "rank": r["rank"]} for r in rows]
        ),
        "calibration_fingerprint": fingerprint(rows),
        "ranked_rows": rows,
        "safety": {
            "research_only": True,
            "production_persist": False,
            "execution_authority": False,
            "eight_e_calls": 0,
            "new_money_calls": 0,
            "trades": 0,
            "orders": 0,
            "portfolio_writes": 0,
        },
    }


def write_snapshot(snapshot: dict[str, Any], history_dir: Path) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    as_of = snapshot["as_of"]
    encoded = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    out = history_dir / f"{as_of}_{snapshot['calibration_fingerprint'][:12]}.json"

    for path in sorted(history_dir.glob(f"{as_of}_*.json")):
        current = path.read_text(encoding="utf-8")
        if path == out and current == encoded:
            return out
        raise SystemExit(f"FAIL duplicate as_of observation: {as_of}:{path}")

    out.write_text(encoded, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--history-dir", required=True)
    args = ap.parse_args()

    artifact, raw = load_artifact(Path(args.artifact))
    snapshot = build_snapshot(artifact, raw)
    out = write_snapshot(snapshot, Path(args.history_dir))

    print("PASS: FUND-13 v3 Scout-native immutable calibration snapshot.")
    print("as_of:", snapshot["as_of"])
    print("source_head:", snapshot["source_head"])
    print("eligible_scored_count:", snapshot["eligible_scored_count"])
    print("calibration_fingerprint:", snapshot["calibration_fingerprint"])
    print("source_artifact_sha256:", snapshot["source_artifact_sha256"])
    print("output:", out)
    print("thresholds_proposed: False")
    print("thresholds_locked: False")
    print("band_policy_applied: False")


if __name__ == "__main__":
    main()
