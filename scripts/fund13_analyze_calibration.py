#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

SNAPSHOT_VERSION = "fund13_calibration_snapshot_3"


def load_snapshots(path: Path) -> list[dict]:
    snapshots = []
    for p in sorted(path.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        if obj.get("snapshot_version") != SNAPSHOT_VERSION:
            continue
        if obj.get("thresholds_proposed") is not False:
            raise SystemExit(f"FAIL threshold proposal in {p}")
        if obj.get("thresholds_locked") is not False:
            raise SystemExit(f"FAIL threshold lock in {p}")
        if obj.get("band_policy_applied") is not False:
            raise SystemExit(f"FAIL band policy in {p}")
        safety = dict(obj.get("safety") or {})
        if safety.get("research_only") is not True:
            raise SystemExit(f"FAIL research_only in {p}")
        if safety.get("production_persist") is not False:
            raise SystemExit(f"FAIL production persist in {p}")
        if safety.get("execution_authority") is not False:
            raise SystemExit(f"FAIL execution authority in {p}")
        for key in ("eight_e_calls", "new_money_calls", "trades", "orders", "portfolio_writes"):
            if int(safety.get(key) or 0):
                raise SystemExit(f"FAIL unsafe snapshot {p}: {key}")
        snapshots.append(obj)

    snapshots.sort(key=lambda x: x["as_of"])
    dates = [s["as_of"] for s in snapshots]
    if len(dates) != len(set(dates)):
        raise SystemExit("FAIL duplicate as_of dates in calibration history")
    return snapshots


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    snaps = load_snapshots(Path(args.history_dir))
    if not snaps:
        raise SystemExit("FAIL no FUND-13 v3 snapshots")

    symbol_obs = defaultdict(list)
    profile_date_members = defaultdict(lambda: defaultdict(list))
    top5_by_date = []
    gaps_by_date = []
    fingerprints = []

    for snap in snaps:
        ranked = list(snap.get("ranked_rows") or [])
        top5_by_date.append((snap["as_of"], {row["fund_code"] for row in ranked[:5]}))
        fingerprints.append({
            "as_of": snap["as_of"],
            "source_head": snap["source_head"],
            "source_artifact_sha256": snap["source_artifact_sha256"],
            "calibration_fingerprint": snap["calibration_fingerprint"],
            "candidate_set_fingerprint": snap["candidate_set_fingerprint"],
        })

        gaps = []
        for idx in range(len(ranked) - 1):
            upper = ranked[idx]
            lower = ranked[idx + 1]
            gap = float(upper["fi_score"]) - float(lower["fi_score"])
            gaps.append({
                "upper_rank": idx + 1,
                "upper_code": upper["fund_code"],
                "upper_score": upper["fi_score"],
                "lower_rank": idx + 2,
                "lower_code": lower["fund_code"],
                "lower_score": lower["fi_score"],
                "gap": gap,
                "midpoint": (float(upper["fi_score"]) + float(lower["fi_score"])) / 2.0,
            })
        if gaps:
            gaps_by_date.append({"as_of": snap["as_of"], **max(gaps, key=lambda x: x["gap"])})

        for row in ranked:
            symbol_obs[row["fund_code"]].append({
                "as_of": snap["as_of"],
                "rank": row["rank"],
                "profile_rank": row.get("profile_rank"),
                "score": row["fi_score"],
                "profile": row.get("fi_profile"),
            })
            profile = str(row.get("fi_profile") or "NONE")
            profile_date_members[profile][snap["as_of"]].append(row)

    adjacent_top5 = []
    for idx in range(len(top5_by_date) - 1):
        left_date, left = top5_by_date[idx]
        right_date, right = top5_by_date[idx + 1]
        adjacent_top5.append({
            "from": left_date,
            "to": right_date,
            "jaccard": jaccard(left, right),
            "overlap": sorted(left & right),
            "added": sorted(right - left),
            "removed": sorted(left - right),
        })

    symbols = {}
    for symbol, obs in sorted(symbol_obs.items()):
        ranks = [float(item["rank"]) for item in obs]
        scores = [float(item["score"]) for item in obs]
        profile_ranks = [float(item["profile_rank"]) for item in obs if item.get("profile_rank") is not None]
        symbols[symbol] = {
            "dates": len(obs),
            "latest_profile": obs[-1]["profile"],
            "mean_rank": mean(ranks),
            "rank_stddev": pstdev(ranks) if len(ranks) > 1 else 0.0,
            "best_rank": int(min(ranks)),
            "worst_rank": int(max(ranks)),
            "mean_score": mean(scores),
            "score_stddev": pstdev(scores) if len(scores) > 1 else 0.0,
            "mean_profile_rank": mean(profile_ranks) if profile_ranks else None,
            "profile_rank_stddev": (
                pstdev(profile_ranks) if len(profile_ranks) > 1
                else 0.0 if profile_ranks else None
            ),
        }

    profiles = {}
    for profile, dates in sorted(profile_date_members.items()):
        counts = [len(rows) for _, rows in sorted(dates.items())]
        scores = [float(row["fi_score"]) for rows in dates.values() for row in rows]
        profiles[profile] = {
            "distinct_dates": len(dates),
            "observations": sum(counts),
            "median_members_per_date": median(counts),
            "mean_score": mean(scores),
            "score_stddev": pstdev(scores) if len(scores) > 1 else 0.0,
            "peer_threshold_review_ready": (len(dates) >= 4 and median(counts) >= 3),
        }

    output = {
        "analysis_version": "fund13_calibration_history_analysis_3",
        "source_contract": "fund14b_candidate_artifact_4",
        "distinct_dates": len(snaps),
        "dates": [snap["as_of"] for snap in snaps],
        "thresholds_proposed": False,
        "thresholds_locked": False,
        "band_policy_applied": False,
        "global_threshold_review_ready": len(snaps) >= 4,
        "global_review_minimum_distinct_dates": 4,
        "peer_review_rule": "at least 4 dates and median >=3 members/date",
        "profiles": profiles,
        "symbols": symbols,
        "adjacent_top5_stability": adjacent_top5,
        "largest_adjacent_gap_by_date": gaps_by_date,
        "fingerprint_history": fingerprints,
        "notice": (
            "Diagnostic/readiness only. "
            "No threshold, cutpoint, recommendation band, trade, or allocation is selected."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=== FUND-13 v3 SCOUT-NATIVE LONGITUDINAL CALIBRATION ===")
    print("distinct_dates:", output["distinct_dates"])
    print("global_threshold_review_ready:", output["global_threshold_review_ready"])
    print("output:", out)
    print("PASS: diagnostic only; no threshold/cutpoint/band selected.")


if __name__ == "__main__":
    main()
