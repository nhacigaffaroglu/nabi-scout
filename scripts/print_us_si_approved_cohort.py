#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.us_si_approved_cohort import (
    validate_approved_us_si_refresh_cohort,
)


def main() -> int:
    symbols = validate_approved_us_si_refresh_cohort()
    print(" ".join(symbols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
