#!/usr/bin/env python3
"""Generate a local FUND15 category-aware research artifact.

No network access. No production persistence. No execution authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from services.turkiye_fund_category_research import build_category_research_artifact

DEFAULT_INPUT = Path(".cache/turkiye_fund_candidate_artifact/last_result.json")
DEFAULT_OUTPUT = Path(".cache/turkiye_fund_category_research/last_result.json")


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

    artifact = build_category_research_artifact(_load_json(args.input))
    _atomic_json(args.output, artifact)

    print("=== FUND-15 CATEGORY-AWARE RESEARCH ARTIFACT v1 ===")
    print("promotion_eligible:", artifact["counts"]["promotion_eligible"])
    print("categories:", artifact["counts"]["categories"])
    for group in artifact["categories"]:
        print(group["category"], [x["fund_code"] for x in group["candidates"]])
    print("write_proof:", artifact["write_proof"])
    print("output:", args.output)
    print("PASS: category-aware research artifact produced; no execution authority.")


if __name__ == "__main__":
    main()
