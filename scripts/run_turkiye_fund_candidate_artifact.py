#!/usr/bin/env python3
"""Generate a local FUND14B research candidate artifact.

No network access. No production persistence. No execution authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from services.turkiye_fund_candidate_artifact import (
    DEFAULT_EXPECTED_SOURCE_HEAD,
    build_candidate_artifact,
)

DEFAULT_INPUT = Path(".cache/turkiye_fund_research_snapshot/last_result.json")
DEFAULT_OUTPUT = Path(".cache/turkiye_fund_candidate_artifact/last_result.json")


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


def _load_threshold_policy(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise SystemExit("threshold policy must be a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold-policy", type=Path)
    parser.add_argument(
        "--expected-source-head",
        default=DEFAULT_EXPECTED_SOURCE_HEAD,
        help="Exact FUND14A source_head expected by this regenerated core.",
    )
    parser.add_argument(
        "--allow-any-source-head",
        action="store_true",
        help="Explicitly disable exact source_head pinning; schema/firewalls still apply.",
    )
    args = parser.parse_args()

    snapshot = _load_json(args.input)
    artifact = build_candidate_artifact(
        snapshot,
        threshold_policy=_load_threshold_policy(args.threshold_policy),
        expected_source_head=(
            None if args.allow_any_source_head else args.expected_source_head
        ),
    )
    _atomic_json(args.output, artifact)

    print("=== FUND-14B CANDIDATE ARTIFACT CORE v4 (REGENERATED) ===")
    print("source_head:", artifact["source"]["source_head"])
    print("as_of:", artifact["source"]["as_of"])
    print("candidate_count:", artifact["counts"]["eligible_candidates"])
    print("promotion_gate:", artifact["promotion_gate"])
    print("promotion_eligible:", artifact["counts"]["promotion_eligible"])
    print("write_proof:", artifact["write_proof"])
    print("output:", args.output)
    print("PASS: research candidate artifact produced; no execution authority.")


if __name__ == "__main__":
    main()
