"""CLI runner for FUND18 descriptive portfolio-fit research."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.turkiye_fund_portfolio_fit_research import (
    build_evidence_backed_portfolio_fit_research_artifact,
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build FUND18 descriptive portfolio-fit research artifact."
    )
    parser.add_argument(
        "--fund17-input",
        required=True,
        help="Path to FUND17 portfolio-fit artifact JSON.",
    )
    parser.add_argument(
        "--evidence-input",
        required=True,
        help="Path to FUND18 evidence/provenance JSON.",
    )
    parser.add_argument(
        "--freshness-policy-input",
        required=False,
        help=(
            "Optional path to an explicit human-approved "
            "FUND18 evidence freshness policy JSON."
        ),
    )
    parser.add_argument(
        "--output",
        default=".cache/turkiye_fund_portfolio_fit_research/last_result.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    fund17_path = Path(args.fund17_input)
    evidence_path = Path(args.evidence_input)
    freshness_policy_path = (
        Path(args.freshness_policy_input)
        if args.freshness_policy_input
        else None
    )
    output_path = Path(args.output)

    fund17_artifact = _read_json(fund17_path)
    evidence = _read_json(evidence_path)
    freshness_policy = (
        _read_json(freshness_policy_path)
        if freshness_policy_path is not None
        else None
    )

    result = build_evidence_backed_portfolio_fit_research_artifact(
        fund17_artifact,
        assessments={},
        evidence=evidence,
        freshness_policy=freshness_policy,
    )

    _write_json_atomic(output_path, result)

    print(f"schema_version={result['schema_version']}")
    print(f"portfolio_fit_status={result['portfolio_fit_status']}")
    print(f"candidates={result['counts']['candidates']}")
    print(
        "descriptive_assessments="
        f"{result['counts']['descriptive_assessments']}"
    )
    print(f"research_only={result['research_only']}")
    print(f"execution_authority={result['execution_authority']}")
    print(f"production_persist={result['production_persist']}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
