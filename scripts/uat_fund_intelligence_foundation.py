#!/usr/bin/env python3
"""Read-only Fund/ETF foundation UAT for SPUS/SPSK/SPRE/SPWO.

No production writes, no New Money persistence, no scheduler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fund_decision_readiness import (
    evaluate_fund_eight_e_readiness,
    evaluate_fund_new_money_readiness,
)
from services.fund_lookthrough_summary import build_fund_lookthrough_summary
from services.fund_portfolio_overlap import build_fund_portfolio_overlap
from services.fund_product_contract import PILOT_FUND_SYMBOLS
from services.official_fund_holdings_client import OfficialFundHoldingsClient, OfficialHoldingsError
from services.official_sp_funds_product import (
    OfficialSpFundsProductProvider,
    fund_intelligence_readiness,
)
from services.portfolio_economic_exposure import classify_instrument_exposure
from tests.fixtures.sp_funds_official import PRODUCT_HTML, PURIFICATION_HTML
from tests.test_official_fund_holdings import _csv, _row
from tests.test_portfolio_economic_exposure import _etf


def _fixture_holdings(symbol: str):
    rows = {
        "SPUS": [
            _row("SPUS", "AAPL", "Apple Inc", "12.00%"),
            _row("SPUS", "NVDA", "NVIDIA", "11.00%"),
            _row("SPUS", "MSFT", "Microsoft", "10.00%"),
            _row("SPUS", "AVGO", "Broadcom", "8.00%"),
            _row("SPUS", "Cash&Other", "Cash & Other", "1.50%", cusip="Cash&Other"),
            "08/28/2026,SPUS,GOOGL,38259P508,Alphabet,1,1,1,57.50%,1,1,1",
        ],
        "SPSK": [_row("SPSK", "BT6MTT4", "KSA Sukuk", "100.00%", cusip="BT6MTT4")],
        "SPRE": [_row("SPRE", "EQIX", "Equinix", "100.00%")],
        "SPWO": [
            _row("SPWO", "005930 KS", "Samsung Electronics", "40.00%", cusip="6771720"),
            "08/28/2026,SPWO,,633517442,Nestle SA,1,1,1,60.00%,1,1,1",
        ],
    }
    from services.official_fund_holdings_client import parse_official_holdings_csv

    return parse_official_holdings_csv(_csv(symbol, rows[symbol]), fund_symbol=symbol)


def main() -> int:
    provider = OfficialSpFundsProductProvider(
        product_html=PRODUCT_HTML,
        purification_html=PURIFICATION_HTML,
    )
    live_holdings = {}
    source_status = {}
    try:
        client = OfficialFundHoldingsClient()
        for symbol in PILOT_FUND_SYMBOLS:
            try:
                live_holdings[symbol] = client.fetch(symbol)
                source_status[symbol] = "official_live"
            except OfficialHoldingsError as exc:
                live_holdings[symbol] = _fixture_holdings(symbol)
                source_status[symbol] = f"fixture:{exc}"
    except Exception as exc:
        for symbol in PILOT_FUND_SYMBOLS:
            live_holdings[symbol] = _fixture_holdings(symbol)
            source_status[symbol] = f"fixture:{exc}"

    report = []
    mandates = {}
    for symbol in PILOT_FUND_SYMBOLS:
        facts = provider.facts(symbol)
        identity = provider.identity(symbol)
        mandate = provider.mandate(symbol)
        mandates[symbol] = mandate
        sharia = provider.sharia_evidence(symbol)
        purification = provider.purification_evidence(symbol)
        holdings = live_holdings[symbol]
        lookthrough = build_fund_lookthrough_summary(
            holdings,
            known_nabi_symbols=("AAPL", "AVGO", "MSFT", "CRM"),
        )
        exposure = classify_instrument_exposure(
            _etf(symbol),
            fund_mandates={symbol: mandate},
        )
        readiness = fund_intelligence_readiness(
            facts=facts,
            mandate=mandate,
            sharia=sharia,
            purification=purification,
            lookthrough_unknown_pct=lookthrough.unknown_weight_pct,
            official_performance_present=True,
        )
        eight_e = evaluate_fund_eight_e_readiness(
            symbol=symbol,
            fund_intelligence_ready=False,
            participation_acceptable=False,
            economic_exposure_available=exposure.evidence_complete,
        )
        new_money = evaluate_fund_new_money_readiness(
            mandate=mandate,
            hybrid_off=True,
            exposure_complete=exposure.evidence_complete,
        )
        report.append(
            {
                "symbol": symbol,
                "identity": identity.to_dict(),
                "facts": facts.to_dict(),
                "holdings_as_of": holdings.as_of.isoformat(),
                "holdings_count": len(holdings.holdings),
                "holdings_source": source_status[symbol],
                "mandate": mandate.to_dict(),
                "sharia": sharia.to_dict(),
                "purification": purification.to_dict(),
                "lookthrough": lookthrough.to_dict(),
                "exposure_complete": exposure.evidence_complete,
                "exposure_bucket": exposure.economic_exposures[0].exposure_bucket,
                "fund_intelligence": readiness.to_dict(),
                "eight_e": eight_e,
                "new_money": new_money,
            }
        )
    overlap = build_fund_portfolio_overlap(
        [
            {"symbol": "AAPL", "weight_pct": 8.0, "asset_class": "equity"},
            {"symbol": "AVGO", "weight_pct": 4.0, "asset_class": "equity"},
            {"symbol": "SPUS", "weight_pct": 30.0, "asset_class": "etf"},
            {"symbol": "SPSK", "weight_pct": 15.0, "asset_class": "etf"},
            {"symbol": "SPRE", "weight_pct": 10.0, "asset_class": "etf"},
            {"symbol": "SPWO", "weight_pct": 10.0, "asset_class": "etf"},
        ],
        live_holdings,
    )
    print(
        json.dumps(
            {
                "writes": 0,
                "paid_api": False,
                "funds": report,
                "overlap": overlap.to_dict(),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
