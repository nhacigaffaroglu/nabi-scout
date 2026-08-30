"""Captured official SP Funds holdings CSVs.

Uses the canonical OfficialFundHoldingsClient parser. No second holdings model.
"""

from __future__ import annotations

from pathlib import Path

from services.official_fund_holdings_client import (
    OfficialHoldingsFile,
    official_holdings_url,
    parse_official_holdings_csv,
)

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_holdings_evidence"


def official_holdings_csv_path(symbol: str) -> Path:
    return EVIDENCE_DIR / f"{str(symbol or '').strip().upper()}.csv"


def load_official_holdings_file(symbol: str) -> OfficialHoldingsFile:
    fund = str(symbol or "").strip().upper()
    path = official_holdings_csv_path(fund)
    if not path.is_file():
        raise FileNotFoundError(f"captured official holdings missing for {fund}")
    return parse_official_holdings_csv(
        path.read_text(encoding="utf-8-sig"),
        fund_symbol=fund,
        source_reference=official_holdings_url(fund),
    )


def default_official_holdings_files() -> dict[str, OfficialHoldingsFile]:
    from services.fund_product_contract import PILOT_FUND_SYMBOLS

    out: dict[str, OfficialHoldingsFile] = {}
    for symbol in PILOT_FUND_SYMBOLS:
        try:
            out[symbol] = load_official_holdings_file(symbol)
        except (FileNotFoundError, OSError):
            continue
    return out
