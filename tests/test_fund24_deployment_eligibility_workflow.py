from pathlib import Path
import unittest


WORKFLOW = Path(
    ".github/workflows/fund24_deployment_eligibility.yml"
)
SERVICE = Path(
    "services/turkiye_fund_deployment_eligibility.py"
)


class Fund24WorkflowTests(unittest.TestCase):
    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file())

    def test_workflow_is_path_scoped(self):
        text = WORKFLOW.read_text()

        self.assertIn(
            "services/turkiye_fund_deployment_eligibility.py",
            text,
        )
        self.assertIn(
            "tests/test_turkiye_fund_deployment_eligibility.py",
            text,
        )
        self.assertIn(
            "tests/test_fund24_deployment_eligibility_workflow.py",
            text,
        )

    def test_workflow_is_read_only(self):
        text = WORKFLOW.read_text()
        self.assertIn("contents: read", text)

    def test_workflow_runs_focused_tests_and_compile(self):
        text = WORKFLOW.read_text()

        self.assertIn(
            "test_turkiye_fund_deployment_eligibility.py",
            text,
        )
        self.assertIn(
            "test_fund24_deployment_eligibility_workflow.py",
            text,
        )
        self.assertIn(
            "py_compile",
            text,
        )

    def test_service_has_no_allocation_authority(self):
        text = SERVICE.read_text()

        forbidden = (
            "allocate_new_money(",
            "build_nabi_recommendation(",
            "build_nabi_decision_v3(",
            "AllocationPlan(",
            "AllocationRecommendation(",
            "record_recommendation(",
            "supabase",
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_service_preserves_canonical_action_boundary(self):
        text = SERVICE.read_text()

        self.assertIn(
            "DECISION_CONSIDER_NEW_POSITION",
            text,
        )
        self.assertIn(
            "DECISION_CONSIDER_TOP_UP",
            text,
        )
        self.assertIn(
            "recommendation_canonical_decision_mismatch",
            text,
        )

    def test_service_preserves_rank_provenance(self):
        text = SERVICE.read_text()

        self.assertIn(
            "deployment_rank_provenance_mismatch",
            text,
        )
        self.assertIn(
            "recommendation_source_rank",
            text,
        )
        self.assertIn(
            "canonical_decision_source_rank",
            text,
        )
        self.assertIn(
            "decision_evaluation_source_rank",
            text,
        )
        self.assertIn(
            "decision_rank",
            text,
        )

    def test_workflow_asserts_zero_allocation_calls(self):
        text = WORKFLOW.read_text()

        self.assertIn(
            'result["write_proof"]["allocation_calls"] == 0',
            text,
        )
        self.assertIn(
            'result["write_proof"]["new_money_calls"] == 0',
            text,
        )


if __name__ == "__main__":
    unittest.main()
