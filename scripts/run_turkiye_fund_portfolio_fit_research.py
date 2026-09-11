"""CLI runner for FUND18 descriptive portfolio-fit research."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.turkiye_fund_portfolio_fit_research import (
    build_portfolio_fit_research_artifact,
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
        "--assessments-input",
        required=True,
        help="Path to explicit descriptive assessments JSON.",
    )
    parser.add_argument(
        "--output",
        default=".cache/turkiye_fund_portfolio_fit_research/last_result.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    fund17_path = Path(args.fund17_input)
    assessments_path = Path(args.assessments_input)
    output_path = Path(args.output)

    fund17_artifact = _read_json(fund17_path)
    assessments = _read_json(assessments_path)

    result = build_portfolio_fit_research_artifact(
        fund17_artifact,
        assessments=assessments,
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
