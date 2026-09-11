#!/usr/bin/env python3
"""Generate local FUND16 within-category comparison artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from services.turkiye_fund_category_comparison import build_category_comparison_artifact

DEFAULT_INPUT = Path(".cache/turkiye_fund_category_research/last_result.json")
DEFAULT_OUTPUT = Path(".cache/turkiye_fund_category_comparison/last_result.json")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    artifact = build_category_comparison_artifact(_load_json(args.input))
    _atomic_json(args.output, artifact)

    print("=== FUND-16 WITHIN-CATEGORY COMPARISON ARTIFACT v1 ===")
    print("promotion_eligible:", artifact["counts"]["promotion_eligible"])
    print("categories:", artifact["counts"]["categories"])
    print("peer_comparable_categories:", artifact["counts"]["peer_comparable_categories"])
    for group in artifact["categories"]:
        print(
            group["category"],
            [
                (
                    x["fund_code"],
                    x["fi_category_rank"],
                    x["return_1y_rank"],
                    x["drawdown_resilience_rank"],
                )
                for x in group["candidates"]
            ],
        )
    print("write_proof:", artifact["write_proof"])
    print("output:", args.output)
    print("PASS: descriptive category comparison produced; no recommendation or execution authority.")


if __name__ == "__main__":
    main()
