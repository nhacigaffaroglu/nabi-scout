from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.fund_intelligence_contract import FundHoldingRow
from services.official_fund_holdings_client import (
    OfficialHoldingsError,
    parse_official_holdings_csv,
)
from services.official_fund_holdings_ingest import (
    OfficialFundHoldingsIngestService,
    OfficialHoldingsWriteGuard,
    OfficialHoldingsWriteGuardError,
    audit_official_file,
    official_rows_to_persist,
)
from services.portfolio_economic_exposure import (
    _HOLDING_ASSET_TYPE_MAP,
    classify_instrument_exposure,
)
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
)
from services.security_master_service import SecurityMasterService
from tests.test_portfolio_economic_exposure import _etf, _snapshot
from tests.test_security_master import _listing


CLIENT = Path("services/official_fund_holdings_client.py")
INGEST = Path("services/official_fund_holdings_ingest.py")
SCRIPT = Path("scripts/refresh_official_fund_holdings.py")
PARTICIPATION = Path("services/universe_expansion_onboarding_service.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")


def _csv(symbol: str, rows: list[str], header: str | None = None) -> str:
    head = header or (
        "Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,"
        "Weightings,NetAssets,SharesOutstanding,CreationUnits"
    )
    return "\n".join([head, *rows]) + "\n"


def _row(
    symbol: str,
    ticker: str,
    name: str,
    weight: str,
    *,
    cusip: str = "037833100",
    day: str = "08/28/2026",
) -> str:
    return f'{day},{symbol},{ticker},{cusip},"{name}",1,1,1,{weight},1,1,1'


class MemoryFundRepo:
    def __init__(self) -> None:
        self.snapshots: Dict[tuple, Dict[str, Any]] = {}
        self.holdings: Dict[str, List[Dict[str, Any]]] = {}
        self._ids = 0

    def upsert_snapshot(self, **payload) -> Dict[str, Any]:
        key = (
            str(payload["fund_symbol"]).upper(),
            payload["as_of"].isoformat() if hasattr(payload["as_of"], "isoformat") else str(payload["as_of"]),
            payload["source"],
        )
        existing = self.snapshots.get(key)
        if existing is None:
            self._ids += 1
            row = {"id": f"snap-{self._ids}", **payload, "as_of": key[1], "fund_symbol": key[0]}
            self.snapshots[key] = row
            return row
        existing.update(
            {
                "coverage_pct": payload.get("coverage_pct"),
                "underlying_count": payload.get("underlying_count"),
            }
        )
        return existing

    def get_snapshot_for_date(self, **kwargs) -> Optional[Dict[str, Any]]:
        key = (
            str(kwargs["fund_symbol"]).upper(),
            kwargs["as_of"].isoformat() if hasattr(kwargs["as_of"], "isoformat") else str(kwargs["as_of"]),
            kwargs["source"],
        )
        return self.snapshots.get(key)

    def replace_holdings(self, snapshot_id: str, holdings: List[Dict[str, Any]]) -> int:
        self.holdings[snapshot_id] = list(holdings)
        return len(holdings)

    def list_holdings(self, snapshot_id: str) -> List[Dict[str, Any]]:
        return list(self.holdings.get(snapshot_id, []))

    def get_latest_snapshot(self, fund_symbol: str) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.snapshots.values() if row["fund_symbol"] == fund_symbol.upper()]
        if not rows:
            return None
        return sorted(rows, key=lambda item: item["as_of"], reverse=True)[0]


class OfficialParseTests(unittest.TestCase):
    def test_parses_issuer_fields_and_preserves_raw_weight(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPUS", [_row("SPUS", "AAPL", "Apple Inc", "50.07%")]),
            fund_symbol="SPUS",
            source_reference="official-test",
        )
        self.assertEqual(parsed.fund_symbol, "SPUS")
        self.assertEqual(parsed.as_of, date(2026, 8, 28))
        self.assertEqual(parsed.source, "sp_funds_official")
        self.assertEqual(parsed.holdings[0].ticker, "AAPL")
        self.assertEqual(parsed.holdings[0].weight_pct, 50.07)
        self.assertIsNone(parsed.holdings[0].asset_type)
        self.assertEqual(parsed.source_reference, "official-test")

    def test_schema_change_is_blocked(self) -> None:
        with self.assertRaises(OfficialHoldingsError):
            parse_official_holdings_csv(
                "Date,Account,Name\n08/28/2026,SPUS,Apple\n",
                fund_symbol="SPUS",
            )

    def test_identifier_uses_issuer_ticker_not_cusip_guess(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPSK",
                [_row("SPSK", "BT6MTT4", "KSA Sukuk", "10.00%", cusip="BT6MTT4")],
            ),
            fund_symbol="SPSK",
        )
        persist = official_rows_to_persist(parsed)
        self.assertEqual(persist[0].underlying_symbol, "BT6MTT4")
        self.assertIsNone(persist[0].asset_type)


class OfficialSafetyTests(unittest.TestCase):
    def test_no_fund_symbol_classification_shortcut(self) -> None:
        for path in (CLIENT, INGEST, SCRIPT):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('if symbol == "SPSK"', source)
            self.assertNotIn("therefore sukuk", source.lower())
            self.assertNotIn("therefore reit", source.lower())
            self.assertNotIn("FMPClient", source)

    def test_spus_does_not_auto_classify_every_holding_equity(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [
                    _row("SPUS", "AAPL", "Apple Inc", "50.00%"),
                    _row("SPUS", "7203", "Toyota", "50.00%"),
                ],
            ),
            fund_symbol="SPUS",
        )
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("AAPL", cik="320193")])
        report = audit_official_file(parsed, security_master=master)
        self.assertAlmostEqual(report.classification["classified_EQUITY"], 50.0)
        self.assertAlmostEqual(report.classification["UNKNOWN"], 50.0)

    def test_spsk_does_not_auto_classify_sukuk(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPSK", [_row("SPSK", "BT6MTT4", "KSA Sukuk Ltd", "100.00%", cusip="BT6MTT4")]),
            fund_symbol="SPSK",
        )
        report = audit_official_file(parsed, security_master=SecurityMasterService(include_canonical_static=False))
        self.assertEqual(report.classification["classified_SUKUK"], 0)
        self.assertAlmostEqual(report.classification["UNKNOWN"], 100.0)

    def test_spre_does_not_auto_classify_reit(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPRE", [_row("SPRE", "O", "Realty Income REIT", "100.00%")]),
            fund_symbol="SPRE",
        )
        report = audit_official_file(parsed, security_master=SecurityMasterService(include_canonical_static=False))
        self.assertEqual(report.classification["classified_REIT"], 0)
        self.assertAlmostEqual(report.classification["UNKNOWN"], 100.0)

    def test_spwo_international_stays_unknown(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPWO", [_row("SPWO", "005930 KS", "Samsung Electronics", "100.00%", cusip="6771720")]),
            fund_symbol="SPWO",
        )
        report = audit_official_file(parsed, security_master=SecurityMasterService(include_canonical_static=False))
        self.assertEqual(report.classification["classified_EQUITY"], 0)
        self.assertAlmostEqual(report.classification["UNKNOWN"], 100.0)

    def test_security_master_equity_and_etf_facts_are_consumed(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [
                    _row("SPUS", "MSFT", "Microsoft", "60.00%"),
                    _row("SPUS", "QQQ", "Invesco QQQ", "40.00%"),
                ],
            ),
            fund_symbol="SPUS",
        )
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts(
            [
                _listing("MSFT", cik="789019"),
                _listing("QQQ", cik="106783", is_etf=True, name="Invesco QQQ Trust ETF"),
            ]
        )
        report = audit_official_file(parsed, security_master=master)
        self.assertAlmostEqual(report.classification["classified_EQUITY"], 60.0)
        self.assertAlmostEqual(report.classification["classified_ETF"], 40.0)
        self.assertAlmostEqual(report.classification["classified_OTHER"], 40.0)
        self.assertEqual(master.resolve_security("QQQ").instrument_type, INSTRUMENT_ETF)

    def test_explicit_asset_type_precedes_security_master(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPUS", [_row("SPUS", "CASH", "Pathward Financial, Inc.", "100.00%")]),
            fund_symbol="SPUS",
        )
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("CASH", cik="907471", name="Pathward Financial, Inc.")])
        self.assertEqual(master.resolve_security("CASH").instrument_type, INSTRUMENT_EQUITY)
        rows = official_rows_to_persist(parsed)
        rows[0] = type(rows[0])(
            underlying_symbol=rows[0].underlying_symbol,
            underlying_name=rows[0].underlying_name,
            weight_pct=rows[0].weight_pct,
            asset_type="cash",
        )
        from services.official_fund_holdings_ingest import classify_official_holdings

        summary, resolution = classify_official_holdings(rows, security_master=master)
        self.assertAlmostEqual(summary["classified_CASH"], 100.0)
        self.assertEqual(resolution["explicit_holding_fact_rows"], 1)

    def test_cash_and_other_and_ticker_cash(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [
                    _row("SPUS", "Cash&Other", "Cash & Other", "10.00%", cusip="Cash&Other"),
                    _row("SPUS", "CASH", "Pathward Financial, Inc.", "90.00%"),
                ],
            ),
            fund_symbol="SPUS",
        )
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("CASH", cik="907471", name="Pathward Financial, Inc.")])
        report = audit_official_file(parsed, security_master=master)
        persist = official_rows_to_persist(parsed)
        self.assertEqual(persist[0].underlying_symbol, "CASH&OTHER")
        self.assertAlmostEqual(report.classification["UNKNOWN"], 10.0)
        self.assertAlmostEqual(report.classification["classified_EQUITY"], 90.0)
        self.assertEqual(report.classification["classified_CASH"], 0)

    def test_material_overflow_is_blocked(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv("SPUS", [_row("SPUS", "AAPL", "Apple", "101.00%")]),
            fund_symbol="SPUS",
        )
        report = audit_official_file(parsed)
        self.assertFalse(report.weight_valid)
        service = OfficialFundHoldingsIngestService(MemoryFundRepo())
        with self.assertRaises(OfficialHoldingsError):
            service.persist(parsed)

    def test_snapshot_replay_idempotent_and_content_change_detected(self) -> None:
        first = parse_official_holdings_csv(
            _csv("SPUS", [_row("SPUS", "AAPL", "Apple Inc", "100.00%")]),
            fund_symbol="SPUS",
        )
        repo = MemoryFundRepo()
        service = OfficialFundHoldingsIngestService(repo)
        created = service.persist(first)
        replay = service.persist(first)
        self.assertEqual(created.snapshot_inserted, 1)
        self.assertEqual(created.holdings_inserted, 1)
        self.assertEqual(replay.snapshot_inserted, 0)
        self.assertEqual(replay.holdings_inserted, 0)
        self.assertEqual(replay.holdings_unchanged, 1)
        self.assertEqual(len(repo.snapshots), 1)
        changed = parse_official_holdings_csv(
            _csv("SPUS", [_row("SPUS", "MSFT", "Microsoft", "100.00%")]),
            fund_symbol="SPUS",
        )
        blocked = service.persist(changed)
        self.assertTrue(blocked.content_changed)
        self.assertFalse(blocked.persisted) if blocked.blocked_reason else self.assertTrue(blocked.content_changed)
        self.assertEqual(repo.list_holdings("snap-1")[0]["underlying_symbol"], "AAPL")
        replaced = service.persist(changed, allow_content_change=True)
        self.assertTrue(replaced.content_changed)
        self.assertEqual(repo.list_holdings("snap-1")[0]["underlying_symbol"], "MSFT")

    def test_lookthrough_uses_official_rows_and_existing_policy(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [
                    _row("SPUS", "AAPL", "Apple", "50.07%"),
                    _row("SPUS", "MSFT", "Microsoft", "50.07%"),
                ],
            ),
            fund_symbol="SPUS",
        )
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("AAPL", cik="1"), _listing("MSFT", cik="2")])
        rows = official_rows_to_persist(parsed)
        self.assertEqual(rows[0].weight_pct, 50.07)
        view = classify_instrument_exposure(
            _etf("SPUS"),
            fund_snapshots={
                "SPUS": _snapshot(
                    "SPUS",
                    tuple(
                        FundHoldingRow(
                            row.underlying_symbol,
                            row.underlying_name,
                            row.weight_pct,
                            None,
                            None,
                            None,
                        )
                        for row in rows
                    ),
                )
            },
            security_master=master,
        )
        self.assertAlmostEqual(view.economic_exposures[0].weight_pct, 100.0)
        self.assertIn("ISSUER_WEIGHT_ROUNDING_NORMALIZED", view.economic_exposures[0].limitations)

    def test_policy_map_and_neighbors_unchanged(self) -> None:
        self.assertEqual(
            _HOLDING_ASSET_TYPE_MAP["cash"],
            "cash",
        )
        self.assertNotIn("security_master", PARTICIPATION.read_text(encoding="utf-8"))
        self.assertNotIn("official_fund_holdings", PARTICIPATION.read_text(encoding="utf-8"))
        self.assertNotIn("official_fund_holdings", NEW_MONEY.read_text(encoding="utf-8"))
        new_money = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("security_master=security_master", new_money)
        self.assertNotIn("SecurityMasterService()", new_money)

    def test_write_guard_blocks_queue(self) -> None:
        class _Table:
            def upsert(self, *args, **kwargs):
                return {"ok": True}

        class _Client:
            def table(self, name):
                return _Table()

        guarded = OfficialHoldingsWriteGuard(_Client())
        guarded.table("fund_holdings").upsert({})
        with self.assertRaises(OfficialHoldingsWriteGuardError):
            guarded.table("universe_expansion_queue").upsert({})
        with self.assertRaises(OfficialHoldingsWriteGuardError):
            guarded.table("security_master").insert({})


if __name__ == "__main__":
    unittest.main()
