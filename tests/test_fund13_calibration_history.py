from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

CAPTURE = Path("scripts/fund13_capture_calibration.py")
spec = importlib.util.spec_from_file_location("f13capv3", CAPTURE)
cap = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(cap)


def sample_artifact() -> dict:
    candidates = [
        ("AAA", 70.0, "P1"),
        ("BBB", 65.0, "P1"),
        ("CCC", 60.0, "P2"),
        ("DDD", 55.0, "P1"),
    ]
    rows = []
    for rank, (code, score, profile) in enumerate(candidates, start=1):
        rows.append({
            "fund_code": code,
            "candidate_rank": rank,
            "upstream_scanner_rank": rank,
            "fi_score": score,
            "fi_state": "WATCH",
            "fi_profile": profile,
            "peer_view": "PEER_CATEGORY",
            "confidence": 1.0,
            "data_completeness": 1.0,
            "exposure": "equity",
            "scanner_status": "READY",
            "participation": "Uygun",
            "research_allowed": True,
        })
    return {
        "schema_version": "fund14b_candidate_artifact_4",
        "source": {
            "fund14a_schema_version": "fund14a_research_snapshot_3",
            "source_head": "abc",
            "as_of": "2026-09-09",
            "calculated_at": "2026-09-09T00:00:00Z",
        },
        "generated_at": "2026-09-09T00:01:00Z",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "rank_contract": [
            "fi_score_desc",
            "data_completeness_desc",
            "confidence_desc",
            "fund_code_asc",
        ],
        "counts": {
            "scanner_rows": 10,
            "eligible_candidates": 4,
            "excluded_rows": 6,
            "promotion_eligible": 0,
        },
        "candidates": rows,
        "threshold_policy": {
            "locked": False,
            "fi_min": None,
            "source": None,
            "decision_id": None,
        },
        "promotion_gate": {
            "open": False,
            "reasons": ["THRESHOLD_UNLOCKED"],
            "meaning": "research_candidate_promotion_only",
            "execution_authority": False,
        },
        "promotion_eligible": [],
        "upstream_activation": {
            "activation_safe": True,
            "participation_baseline_delta": {
                "baseline_count": 4,
                "current_count": 4,
                "added": [],
                "removed": [],
                "manual_review_required": False,
            },
        },
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_calls": 0,
            "new_money_calls": 0,
        },
    }


class Fund13HistoryTests(unittest.TestCase):
    def write(self, root: Path, obj: dict) -> Path:
        p = root / "artifact.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_valid_artifact_builds_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = self.write(root, sample_artifact())
            artifact, raw = cap.load_artifact(p)
            snap = cap.build_snapshot(artifact, raw)
            self.assertEqual(snap["eligible_scored_count"], 4)
            self.assertFalse(snap["thresholds_locked"])
            self.assertEqual(
                [r["profile_rank"] for r in snap["ranked_rows"]],
                [1, 2, 1, 3],
            )

    def test_locked_threshold_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["threshold_policy"]["locked"] = True
            obj["threshold_policy"]["fi_min"] = 60
            with self.assertRaises(SystemExit):
                cap.load_artifact(self.write(root, obj))

    def test_open_promotion_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["promotion_gate"]["open"] = True
            with self.assertRaises(SystemExit):
                cap.load_artifact(self.write(root, obj))

    def test_nonzero_write_proof_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["write_proof"]["trades"] = 1
            with self.assertRaises(SystemExit):
                cap.load_artifact(self.write(root, obj))

    def test_dirty_participation_delta_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["upstream_activation"]["participation_baseline_delta"]["added"] = ["ZZZ"]
            with self.assertRaises(SystemExit):
                cap.load_artifact(self.write(root, obj))

    def test_recommendation_band_presence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["candidates"][0]["recommendation_band"] = "candidate"
            p = self.write(root, obj)
            artifact, raw = cap.load_artifact(p)
            with self.assertRaises(SystemExit):
                cap.build_snapshot(artifact, raw)

    def test_noncontiguous_rank_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["candidates"][2]["candidate_rank"] = 7
            p = self.write(root, obj)
            artifact, raw = cap.load_artifact(p)
            with self.assertRaises(SystemExit):
                cap.build_snapshot(artifact, raw)

    def test_duplicate_candidate_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            obj["candidates"][1]["fund_code"] = "AAA"
            p = self.write(root, obj)
            artifact, raw = cap.load_artifact(p)
            with self.assertRaises(SystemExit):
                cap.build_snapshot(artifact, raw)

    def test_duplicate_as_of_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = sample_artifact()
            p = self.write(root, obj)
            artifact, raw = cap.load_artifact(p)
            snap = cap.build_snapshot(artifact, raw)
            history = root / "history"
            cap.write_snapshot(snap, history)

            changed = deepcopy(snap)
            changed["ranked_rows"][0]["fi_score"] = 71.0
            changed["calibration_fingerprint"] = cap.fingerprint(changed["ranked_rows"])
            with self.assertRaises(SystemExit):
                cap.write_snapshot(changed, history)


if __name__ == "__main__":
    unittest.main()
