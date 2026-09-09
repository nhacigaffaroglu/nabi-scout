from __future__ import annotations

from pathlib import Path
import unittest

WF = Path(".github/workflows/fund13_calibration_history.yml")


class Fund13WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = WF.read_text(encoding="utf-8")

    def test_chains_from_fund14b_completion(self):
        d = self.data
        self.assertIn('workflows:\n      - "FUND14B Candidate Artifact"', d)
        self.assertIn("workflow_run:", d)
        self.assertIn("- completed", d)

    def test_no_schedule_or_cron(self):
        d = self.data
        self.assertNotIn("\n  schedule:", d)
        self.assertNotIn("cron:", d)

    def test_read_only_permissions(self):
        self.assertIn(
            "permissions:\n  contents: read\n  actions: read",
            self.data,
        )

    def test_exact_upstream_artifact_detection(self):
        d = self.data
        self.assertIn("listWorkflowRunArtifacts", d)
        self.assertIn("fund14b-candidate-artifact-${runId}", d)
        self.assertIn("matches.length > 1", d)
        self.assertIn("artifact_found", d)

    def test_no_production_credentials_or_persist_flags(self):
        d = self.data
        for forbidden in (
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "--persist-fund-intelligence",
            "--persist-participation",
            "--threshold-policy",
            "--allow-any-source-head",
        ):
            self.assertNotIn(forbidden, d)

    def test_thresholds_remain_unselected(self):
        d = self.data
        self.assertIn('assert d["thresholds_proposed"] is False', d)
        self.assertIn('assert d["thresholds_locked"] is False', d)
        self.assertIn('assert d["band_policy_applied"] is False', d)
        self.assertIn('assert d["global_review_minimum_distinct_dates"] == 4', d)

    def test_history_is_actions_artifact_only(self):
        d = self.data
        self.assertIn("fund13_collect_actions_history.py", d)
        self.assertIn("actions/upload-artifact@v4", d)
        self.assertIn("name: fund13-calibration-observation", d)
        self.assertIn("retention-days: 90", d)

    def test_no_execution_terms(self):
        d = self.data
        for forbidden in (
            "place_order",
            "broker",
            "trade_execute",
            "portfolio_write",
            "new_money_execute",
            "eight_e_execute",
        ):
            self.assertNotIn(forbidden, d)


if __name__ == "__main__":
    unittest.main()
