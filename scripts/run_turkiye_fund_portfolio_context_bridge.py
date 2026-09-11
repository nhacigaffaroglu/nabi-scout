"""CLI for FUND17B explicit portfolio-context bridge."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from services.turkiye_fund_portfolio_context_bridge import (
    build_fund17_portfolio_context,
)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        required=True,
        help="Explicit human-approved FUND17B source context JSON",
    )
    parser.add_argument(
        "--output",
        default=".cache/turkiye_fund_portfolio_context/last_result.json",
    )
    args = parser.parse_args()

    result = build_fund17_portfolio_context(_read(Path(args.input)))
    _atomic_write(Path(args.output), result)

    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "human_supplied": result["human_supplied"],
                "research_only": result["research_only"],
                "execution_authority": result["execution_authority"],
                "desired_roles": len(result["desired_roles"]),
                "existing_exposures": len(result["existing_exposures"]),
                "constraints": len(result["constraints"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
