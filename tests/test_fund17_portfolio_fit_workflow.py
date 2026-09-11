from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fund17_portfolio_fit.yml"


class Fund17WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_chain_only_from_fund16_completion(self):
        self.assertIn('workflows:\n      - "FUND16 Category Comparison Artifact"', self.text)
        self.assertIn("types:\n      - completed", self.text)

    def test_live_build_filters_fund16_push_only_runs(self):
        self.assertIn("github.event_name == 'workflow_run'", self.text)
        self.assertIn("github.event.workflow_run.event == 'workflow_run'", self.text)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.text)

    def test_read_only_permissions_and_actions_read(self):
        self.assertIn("contents: read", self.text)
        self.assertIn("actions: read", self.text)
        self.assertNotIn("contents: write", self.text)

    def test_exact_fund16_head_checkout(self):
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", self.text)

    def test_exact_cross_run_fund16_artifact_download(self):
        self.assertIn(
            "name: fund16-category-comparison-${{ github.event.workflow_run.id }}",
            self.text,
        )
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", self.text)
        self.assertIn("github-token: ${{ secrets.GITHUB_TOKEN }}", self.text)

    def test_no_portfolio_context_is_invented_or_downloaded(self):
        self.assertNotIn("--portfolio-context", self.text)
        self.assertNotIn("fund17_portfolio_context_1", self.text)
        self.assertIn("PORTFOLIO_CONTEXT_REQUIRED", self.text)

    def test_upstream_fi60_provenance_is_validated(self):
        self.assertIn('assert threshold.get("locked") is True', self.text)
        self.assertIn('assert threshold.get("fi_min") == 60.0', self.text)
        self.assertIn(
            'assert threshold.get("decision_id") == "FUND14B-FI60-2026-09-11"',
            self.text,
        )

    def test_fund17_has_no_fit_scores_rank_winner_or_recommendation(self):
        self.assertIn('assert d.get("portfolio_fit_winner") is None', self.text)
        self.assertIn('assert d.get("portfolio_fit_composite_score") is None', self.text)
        self.assertIn('assert d.get("recommendation") is None', self.text)
        self.assertIn('assert row.get("role_fit") is None', self.text)
        self.assertIn('assert row.get("economic_overlap") is None', self.text)
        self.assertIn('assert row.get("diversification_contribution") is None', self.text)
        self.assertIn('assert row.get("concentration_risk") is None', self.text)
        self.assertIn('assert row.get("portfolio_fit_rank") is None', self.text)

    def test_zero_write_firewall_is_validated(self):
        for key in (
            "production_writes",
            "trade_actions",
            "orders",
            "portfolio_writes",
            "eight_e_calls",
            "new_money_calls",
        ):
            self.assertIn(f'"{key}": 0', self.text)

    def test_no_production_credentials_or_persist_calls(self):
        upper = self.text.upper()
        self.assertNotIn("SUPABASE_SERVICE_ROLE", upper)
        self.assertNotIn("SUPABASE_SERVICE_KEY", upper)
        self.assertNotIn("PRODUCTION_PERSIST: TRUE", upper)

    def test_evidence_artifact_uploaded(self):
        self.assertIn("fund17-portfolio-fit-${{ github.run_id }}", self.text)
        self.assertIn(".artifacts/fund17/portfolio_fit_artifact.json", self.text)
        self.assertIn(".artifacts/fund17/run.log", self.text)


if __name__ == "__main__":
    unittest.main()
