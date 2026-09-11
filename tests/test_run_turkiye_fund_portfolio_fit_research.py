import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_turkiye_fund_portfolio_fit_research.py"


def zero_proof():
    return {
        "production_writes": 0,
        "trade_actions": 0,
        "orders": 0,
        "portfolio_writes": 0,
        "eight_e_calls": 0,
        "new_money_calls": 0,
    }


def fund17():
    return {
        "schema_version": "fund17_portfolio_fit_artifact_1",
        "source": {
            "fund16_schema_version":
                "fund16_category_comparison_artifact_1",
            "source": {},
        },
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
        "portfolio_fit_status":
            "READY_FOR_PORTFOLIO_FIT_RESEARCH",
        "portfolio_fit_winner": None,
        "portfolio_fit_composite_score": None,
        "recommendation": None,
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
            }
        ],
        "write_proof": zero_proof(),
    }


def assessments():
    return {
        "IAT": {
            "fund_code": "IAT",
            "role_fit": "STRONG",
            "economic_overlap": "LOW",
            "diversification_contribution": "HIGH",
            "concentration_risk": "LOW",
            "rationale": [
                "Synthetic runner fixture only."
            ],
        }
    }


def source():
    return {
        "source_type": "FUND17_PORTFOLIO_CONTEXT",
        "source_id": "synthetic-context-1",
        "observed_fact": "Synthetic evidence only.",
        "as_of": "2026-09-11T18:00:00Z",
    }


def dimension(state="SUPPORTED"):
    return {
        "state": state,
        "sources": [source()] if state == "SUPPORTED" else [],
        "rationale": [
            f"Synthetic {state.lower()} evidence fixture."
        ],
    }


def evidence(role_state="SUPPORTED"):
    return {
        "IAT": {
            "schema_version":
                "fund18_portfolio_fit_evidence_1",
            "fund_code": "IAT",
            "research_only": True,
            "execution_authority": False,
            "production_persist": False,
            "dimensions": {
                "role_fit": dimension(role_state),
                "economic_overlap": dimension(),
                "diversification_contribution": dimension(),
                "concentration_risk": dimension(),
            },
        }
    }


def freshness_policy(max_age_days=1):
    return {
        "schema_version":
            "fund18_portfolio_fit_freshness_policy_1",
        "human_approved": True,
        "policy_id": "FUND18-RUNNER-FRESHNESS-TEST-1",
        "source_max_age_days": {
            "FUND17_PORTFOLIO_CONTEXT": max_age_days,
        },
    }


def write_json(path, payload):
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def run_runner(
    tmp_path,
    *,
    assessment_payload=None,
    evidence_payload=None,
    freshness_policy_payload=None,
):
    fund17_path = tmp_path / "fund17.json"
    assessments_path = tmp_path / "assessments.json"
    evidence_path = tmp_path / "evidence.json"
    freshness_policy_path = tmp_path / "freshness_policy.json"
    output_path = tmp_path / "result.json"

    write_json(fund17_path, fund17())
    write_json(
        assessments_path,
        assessments()
        if assessment_payload is None
        else assessment_payload,
    )
    write_json(
        evidence_path,
        evidence()
        if evidence_payload is None
        else evidence_payload,
    )

    command = [
        sys.executable,
        str(RUNNER),
        "--fund17-input",
        str(fund17_path),
        "--assessments-input",
        str(assessments_path),
        "--evidence-input",
        str(evidence_path),
    ]

    if freshness_policy_payload is not None:
        write_json(
            freshness_policy_path,
            freshness_policy_payload,
        )
        command.extend(
            [
                "--freshness-policy-input",
                str(freshness_policy_path),
            ]
        )

    command.extend(
        [
            "--output",
            str(output_path),
        ]
    )

    result = subprocess.run(
        command,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
    )

    return result, output_path


def test_runner_writes_evidence_backed_artifact(tmp_path):
    result, output_path = run_runner(tmp_path)

    assert result.returncode == 0, result.stderr
    assert output_path.exists()

    payload = json.loads(output_path.read_text())

    assert (
        payload["schema_version"]
        == "fund18_portfolio_fit_research_artifact_1"
    )
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["production_persist"] is False
    assert payload["write_proof"] == zero_proof()

    row = payload["candidates"][0]

    assert row["role_fit"] == "STRONG"
    assert row["economic_overlap"] == "LOW"
    assert row["portfolio_fit_composite_score"] is None
    assert row["portfolio_fit_rank"] is None
    assert row["recommendation"] is None
    assert (
        row["evidence"]["schema_version"]
        == "fund18_portfolio_fit_evidence_1"
    )


def test_runner_forces_unknown_when_evidence_insufficient(tmp_path):
    result, output_path = run_runner(
        tmp_path,
        evidence_payload=evidence("INSUFFICIENT"),
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(output_path.read_text())
    row = payload["candidates"][0]

    assert row["role_fit"] == "UNKNOWN"
    assert row["economic_overlap"] == "LOW"


def test_invalid_assessment_fails_closed_without_output(tmp_path):
    bad = assessments()
    bad["IAT"]["role_fit"] = "BUY"

    result, output_path = run_runner(
        tmp_path,
        assessment_payload=bad,
    )

    assert result.returncode != 0
    assert not output_path.exists()


def test_invalid_evidence_fails_closed_without_output(tmp_path):
    bad = evidence()
    bad["IAT"]["dimensions"]["role_fit"]["state"] = "GOOD"

    result, output_path = run_runner(
        tmp_path,
        evidence_payload=bad,
    )

    assert result.returncode != 0
    assert not output_path.exists()


def test_runner_applies_explicit_freshness_policy(tmp_path):
    result, output_path = run_runner(
        tmp_path,
        freshness_policy_payload=freshness_policy(1),
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()

    payload = json.loads(output_path.read_text())

    assert (
        payload["evidence_policy"]["freshness_policy_applied"]
        is True
    )
    assert (
        payload["freshness_policy"]["policy_id"]
        == "FUND18-RUNNER-FRESHNESS-TEST-1"
    )
    assert (
        payload["freshness_policy"]["source_max_age_days"][
            "FUND17_PORTFOLIO_CONTEXT"
        ]
        == 1
    )


def test_runner_fails_closed_on_stale_evidence(tmp_path):
    stale = evidence()

    for item in stale["IAT"]["dimensions"].values():
        item["sources"][0]["as_of"] = "2026-09-01T00:00:00Z"

    result, output_path = run_runner(
        tmp_path,
        evidence_payload=stale,
        freshness_policy_payload=freshness_policy(1),
    )

    assert result.returncode != 0
    assert not output_path.exists()
    assert "evidence_stale:" in result.stderr
