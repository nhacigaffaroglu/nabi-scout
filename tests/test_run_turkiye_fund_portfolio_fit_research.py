import json
import subprocess
import sys
from pathlib import Path


ZERO_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "eight_e_calls": 0,
    "new_money_calls": 0,
}


def _fund17():
    return {
        "schema_version": "fund17_portfolio_fit_artifact_1",
        "source": {
            "fund16_schema_version": "fund16_category_comparison_artifact_1",
            "source": {},
        },
        "generated_at": "2026-09-11T18:00:00Z",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "portfolio_context_available": True,
        "portfolio_context": {
            "schema_version": "fund17_portfolio_context_1",
            "human_supplied": True,
            "research_only": True,
            "execution_authority": False,
            "desired_roles": ["diversification"],
            "existing_exposures": ["equity"],
            "constraints": ["research only"],
            "notes": "Synthetic runner fixture.",
        },
        "portfolio_fit_status": "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
        "counts": {
            "candidates": 1,
            "context_ready": 1,
            "context_required": 0,
        },
        "candidates": [
            {
                "fund_code": "IAT",
                "fund_name": "IAT Fund",
                "category": "sukuk",
                "fi_score": 60.49,
                "fi_state": "NEUTRAL",
                "return_1y": 40.76,
                "return_1y_rank": None,
                "max_drawdown": -0.22,
                "drawdown_resilience_rank": None,
                "portfolio_fit_status": "READY_FOR_PORTFOLIO_FIT_RESEARCH",
                "role_fit": None,
                "economic_overlap": None,
                "diversification_contribution": None,
                "concentration_risk": None,
                "portfolio_fit_composite_score": None,
                "portfolio_fit_rank": None,
                "recommendation": None,
            }
        ],
        "write_proof": dict(ZERO_PROOF),
    }


def _assessments():
    return {
        "IAT": {
            "fund_code": "IAT",
            "role_fit": "STRONG",
            "economic_overlap": "LOW",
            "diversification_contribution": "HIGH",
            "concentration_risk": "LOW",
            "rationale": [
                "Synthetic test assessment only; not investment advice."
            ],
        }
    }


def test_runner_writes_expected_artifact(tmp_path: Path):
    fund17_path = tmp_path / "fund17.json"
    assessments_path = tmp_path / "assessments.json"
    output_path = tmp_path / "fund18.json"

    fund17_path.write_text(
        json.dumps(_fund17()),
        encoding="utf-8",
    )
    assessments_path.write_text(
        json.dumps(_assessments()),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_turkiye_fund_portfolio_fit_research.py",
            "--fund17-input",
            str(fund17_path),
            "--assessments-input",
            str(assessments_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == (
        "fund18_portfolio_fit_research_artifact_1"
    )
    assert payload["portfolio_fit_status"] == (
        "DESCRIPTIVE_RESEARCH_COMPLETE"
    )
    assert payload["write_proof"] == ZERO_PROOF
    assert payload["recommendation"] is None
    assert payload["portfolio_fit_winner"] is None

    candidate = payload["candidates"][0]
    assert candidate["fund_code"] == "IAT"
    assert candidate["role_fit"] == "STRONG"
    assert candidate["economic_overlap"] == "LOW"
    assert candidate["diversification_contribution"] == "HIGH"
    assert candidate["concentration_risk"] == "LOW"
    assert candidate["portfolio_fit_composite_score"] is None
    assert candidate["portfolio_fit_rank"] is None
    assert candidate["recommendation"] is None

    assert "research_only=True" in result.stdout
    assert "execution_authority=False" in result.stdout
    assert "production_persist=False" in result.stdout


def test_runner_fails_closed_on_invalid_assessment(tmp_path: Path):
    fund17_path = tmp_path / "fund17.json"
    assessments_path = tmp_path / "assessments.json"
    output_path = tmp_path / "fund18.json"

    bad = _assessments()
    bad["IAT"]["role_fit"] = "BUY"

    fund17_path.write_text(
        json.dumps(_fund17()),
        encoding="utf-8",
    )
    assessments_path.write_text(
        json.dumps(bad),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_turkiye_fund_portfolio_fit_research.py",
            "--fund17-input",
            str(fund17_path),
            "--assessments-input",
            str(assessments_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not output_path.exists()
