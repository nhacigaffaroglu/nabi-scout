#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import os

from services.turkiye_fund_portfolio_fit import build_portfolio_fit_artifact


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as fh:
        fh.write(text)
        tmp = Path(fh.name)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=".cache/turkiye_fund_category_comparison/last_result.json",
    )
    parser.add_argument(
        "--portfolio-context",
        default=None,
        help="Optional explicit human-supplied FUND17 portfolio context JSON",
    )
    parser.add_argument(
        "--output",
        default=".cache/turkiye_fund_portfolio_fit/last_result.json",
    )
    args = parser.parse_args()

    context = _read(Path(args.portfolio_context)) if args.portfolio_context else None
    result = build_portfolio_fit_artifact(
        _read(Path(args.input)),
        portfolio_context=context,
    )
    _atomic_write(Path(args.output), result)
    print(json.dumps(result["counts"], sort_keys=True))
    print("portfolio_fit_status:", result["portfolio_fit_status"])


if __name__ == "__main__":
    main()
