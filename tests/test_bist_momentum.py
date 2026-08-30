from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import unittest

from services.bist_corporate_action_audit import (
    EVENT_BONUS,
    EVENT_CASH_DIVIDEND,
    OfficialCorporateAction,
    STATUS_UNRESOLVED,
    official_bonus_or_split_factor,
)
from services.bist_eod_bulletin import parse_thb_csv, thb_download_url
from services.bist_momentum_facts import MOMENTUM_FIELDS, momentum_from_bist_history
from services.bist_si_readiness import DIM_MOMENTUM, STATUS_BLOCKED, audit_bist_si_readiness
from services.bist_thb_history import (
    DEFAULT_CACHE_DIR,
    ThbHistoryCache,
    ingest_thb_text,
    load_cached_series,
    series_from_bulletins,
)
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.kap_financial_bridge import kap_security_facts_payload
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_parser import parse_public_kap_html
from services.local_market_history_service import HORIZONS, compute_local_momentum
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import AUTHORITY_BORSA_ISTANBUL, AUTHORITY_SEC
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.bist_thb_history_days import (
    equity_row,
    historical_row,
    thb_csv,
    weekday_series,
)
from tests.fixtures.kap_eps_fy_rows import asels_unresolved_eps_html, bimas_tam_tl_eps_html


END = date(2026, 8, 19)
FACTS = Path("services/security_facts_service.py")
HISTORY = Path("services/bist_thb_history.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
SI = Path("services/security_intelligence_engine.py")


def _bundle(symbol: str, series, events=()):
    return momentum_from_bist_history(series, symbol=symbol, official_events=events, as_of=END)


class ThbHistoryParserTests(unittest.TestCase):
    def test_daily_parser_and_e_series_try(self) -> None:
        text = thb_csv(
            END,
            [
                equity_row(END, "ASELS", 403.0),
                equity_row(END, "BIMAS", 416.5),
            ],
        )
        bulletin = parse_thb_csv(text, source_file="thb202608191.csv", source_url=thb_download_url(END))
        self.assertEqual(bulletin.quotes["ASELS"].instrument_series, "ASELS.E")
        self.assertEqual(bulletin.quotes["ASELS"].currency, "TRY")
        self.assertEqual(bulletin.quotes["ASELS"].closing_price, 403.0)

    def test_multi_day_ordering_and_duplicates(self) -> None:
        first = END - timedelta(days=1)
        days = [
            parse_thb_csv(
                thb_csv(first, [equity_row(first, "TUPRS", 390.0)]),
                source_file="a.csv",
                source_url="https://borsaistanbul.com/data/thb/a.zip",
            ),
            parse_thb_csv(
                thb_csv(END, [equity_row(END, "TUPRS", 395.5)]),
                source_file="b.csv",
                source_url="https://borsaistanbul.com/data/thb/b.zip",
            ),
        ]
        series = series_from_bulletins(days, "TUPRS")
        self.assertEqual([item.trade_date for item in series], [first, END])
        dup = (
            historical_row("TUPRS", END, 395.5),
            historical_row("TUPRS", END, 396.0),
        )
        blocked = _bundle("TUPRS", dup)
        self.assertEqual(blocked.blocked_reason, "DUPLICATE_TRADE_DATE")
        self.assertIsNone(blocked.momentum.values["return_3m"])

    def test_incremental_cache_does_not_refetch(self) -> None:
        root = Path("tests/fixtures/_tmp_thb_cache")
        if root.exists():
            for path in root.glob("*"):
                path.unlink()
            root.rmdir()
        cache = ThbHistoryCache(root=root)
        ingest_thb_text(
            thb_csv(END, [equity_row(END, "ASELS", 403.0)]),
            source_file="thb202608191.csv",
            source_url=thb_download_url(END),
            cache=cache,
        )
        self.assertTrue(cache.csv_path(END).is_file())
        loaded = load_cached_series(cache, "ASELS")
        self.assertEqual(loaded[0].close, 403.0)
        source = HISTORY.read_text(encoding="utf-8")
        self.assertIn("date_is_cached(cache, trading_date) and not invalidate", source)
        for path in root.glob("*"):
            path.unlink()
        root.rmdir()


class LookbackAndMetricTests(unittest.TestCase):
    def test_weekend_uses_nearest_eligible_trading_date(self) -> None:
        series = weekday_series("ASELS", end=END, calendar_days=120, start_price=100.0, daily_step=0.2)
        bundle = _bundle("ASELS", series)
        spec = HORIZONS["return_3m"]
        self.assertIsNotNone(bundle.momentum.values["return_3m"])
        anchor = bundle.anchors["return_3m"]
        start = date.fromisoformat(anchor["start_date"])
        gap = (END - start).days
        self.assertGreaterEqual(gap, spec["min_days"])
        self.assertLessEqual(gap, spec["max_days"])
        self.assertEqual(start.weekday(), min(start.weekday(), 4))

    def test_insufficient_horizons(self) -> None:
        short = weekday_series("BIMAS", end=END, calendar_days=40, start_price=400.0, daily_step=0.2)
        mid = weekday_series("BIMAS", end=END, calendar_days=120, start_price=400.0, daily_step=0.2)
        longish = weekday_series("BIMAS", end=END, calendar_days=200, start_price=400.0, daily_step=0.2)
        self.assertIsNone(_bundle("BIMAS", short).momentum.values["return_3m"])
        self.assertIsNone(_bundle("BIMAS", mid).momentum.values["return_6m"])
        self.assertIsNone(_bundle("BIMAS", longish).momentum.values["return_1y"])

    def test_canonical_returns_and_drawdown(self) -> None:
        series = weekday_series("TUPRS", end=END, calendar_days=400, start_price=100.0, daily_step=0.05)
        bundle = _bundle("TUPRS", series)
        observations = __import__(
            "services.bist_momentum_facts", fromlist=["observations_from_history"]
        ).observations_from_history(series)
        expected = compute_local_momentum(observations)
        for field in ("return_3m", "return_6m", "return_1y", "drawdown"):
            self.assertEqual(bundle.momentum.values[field], expected.values[field])
            self.assertIsNotNone(bundle.momentum.values[field])
        self.assertIn("running_peak", bundle.anchors["drawdown"]["formula"])

    def test_stale_history_is_flagged(self) -> None:
        old_end = date(2026, 6, 1)
        series = weekday_series("ASELS", end=old_end, calendar_days=30, start_price=300.0)
        quality = _bundle("ASELS", series).quality
        self.assertTrue(quality["stale"] or quality["observations"] > 0)
        late = momentum_from_bist_history(series, symbol="ASELS", as_of=END)
        self.assertTrue(late.quality["stale"])


class CorporateActionTests(unittest.TestCase):
    def test_unresolved_thb_flag_blocks_metrics(self) -> None:
        series = list(weekday_series("ASELS", end=END, calendar_days=400, start_price=100.0, daily_step=0.05))
        flagged = next(row for row in reversed(series) if (END - row.trade_date).days <= 40)
        idx = series.index(flagged)
        series[idx] = historical_row(flagged.symbol, flagged.trade_date, flagged.close, corporate_action_flag="06")
        bundle = _bundle("ASELS", series)
        self.assertEqual(bundle.adjustment_status, STATUS_UNRESOLVED)
        self.assertIsNone(bundle.momentum.values["return_3m"])
        self.assertIsNone(bundle.momentum.values["return_6m"])
        self.assertIsNone(bundle.momentum.values["return_1y"])
        self.assertIsNone(bundle.momentum.values["drawdown"])

    def test_official_bonus_adjusts_price_return(self) -> None:
        series = list(weekday_series("BIMAS", end=END, calendar_days=400, start_price=200.0, daily_step=0.0))
        event_day = END - timedelta(days=30)
        for idx, row in enumerate(series):
            if row.trade_date >= event_day:
                series[idx] = historical_row(row.symbol, row.trade_date, 100.0)
        event = OfficialCorporateAction(
            symbol="BIMAS",
            event_type=EVENT_BONUS,
            effective_date=event_day,
            official_source="https://www.borsaistanbul.com/files/teorik-fiyatlarin-belirlenmesi-03-04-2026.pdf",
            ratio=Decimal("1"),
            adjustment_required=True,
        )
        self.assertEqual(official_bonus_or_split_factor(Decimal("1")), Decimal("0.5"))
        raw = _bundle("BIMAS", series)
        adjusted = _bundle("BIMAS", series, (event,))
        self.assertLess(raw.momentum.values["return_3m"], -30)
        self.assertAlmostEqual(adjusted.momentum.values["return_3m"], 0.0, places=2)
        self.assertNotIn("yahoo", Path("services/bist_corporate_action_audit.py").read_text(encoding="utf-8").casefold())
        self.assertNotIn("tradingview", Path("services/bist_momentum_facts.py").read_text(encoding="utf-8").casefold())

    def test_typed_kap_event_supersedes_thb_flag(self) -> None:
        series = list(weekday_series("ASELS", end=END, calendar_days=400, start_price=100.0, daily_step=0.05))
        row = next(item for item in reversed(series) if (END - item.trade_date).days <= 40)
        series[series.index(row)] = historical_row("ASELS", row.trade_date, row.close, corporate_action_flag="06")
        dividend = OfficialCorporateAction(
            symbol="ASELS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=row.trade_date,
            official_source="https://www.kap.org.tr/tr/Bildirim/1443371",
            adjustment_required=False,
        )
        blocked = _bundle("ASELS", series)
        allowed = _bundle("ASELS", series, (dividend,))
        self.assertIsNone(blocked.momentum.values["return_3m"])
        self.assertIsNotNone(allowed.momentum.values["return_3m"])

    def test_cash_dividend_does_not_adjust_price_return(self) -> None:
        series = weekday_series("TUPRS", end=END, calendar_days=120, start_price=100.0, daily_step=0.0)
        event = OfficialCorporateAction(
            symbol="TUPRS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=END - timedelta(days=10),
            official_source="https://www.borsaistanbul.com/files/teorik-fiyatlarin-belirlenmesi-03-04-2026.pdf",
            amount=Decimal("5"),
            adjustment_required=False,
        )
        bundle = _bundle("TUPRS", series, (event,))
        self.assertIsNotNone(bundle.momentum.values["return_3m"])
        self.assertAlmostEqual(bundle.momentum.values["return_3m"], 0.0, places=4)


class SecurityFactsAndIsolationTests(unittest.TestCase):
    def test_securityfacts_wires_official_momentum(self) -> None:
        series = weekday_series("TUPRS", end=END, calendar_days=400, start_price=300.0, daily_step=0.1)
        facts = SecurityFactsService().build(
            "TUPRS",
            bist_price_history=series,
            allow_sec_cache_replay=False,
        )
        self.assertIsNotNone(facts.return_3m)
        self.assertIsNotNone(facts.return_6m)
        self.assertIsNotNone(facts.return_1y)
        self.assertIsNotNone(facts.drawdown)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["return_3m"].authority, AUTHORITY_BORSA_ISTANBUL)
        self.assertEqual(by_field["return_3m"].source, "borsa_istanbul_thb")
        audit = audit_bist_si_readiness(facts)
        self.assertEqual(audit.dimensions[DIM_MOMENTUM], "READY")
        self.assertFalse(audit.persisted)

    def test_asels_pe_remains_blocked(self) -> None:
        series = weekday_series("ASELS", end=END, calendar_days=400, start_price=350.0)
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload(
                ingest_public_kap_financials(
                    parse_public_kap_html(
                        asels_unresolved_eps_html(),
                        symbol="ASELS",
                        disclosure_id="1561039",
                        cached=True,
                    )
                )
            ),
            bist_price_history=series,
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)
        self.assertIsNotNone(facts.return_3m)

    def test_us_isolation_and_no_default_fetch(self) -> None:
        aapl = SecurityFactsService().build(
            "AAPL",
            sec_financials={"eps": 6.0, "revenue": 400.0, "financial_currency": "USD"},
            candidate={"current_price": 180.0},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(aapl.eps, 6.0)
        self.assertEqual(aapl.pe, 30.0)
        self.assertEqual({item.field: item for item in aapl.provenance}["eps"].authority, AUTHORITY_SEC)
        crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertNotEqual(crm.currency, "TRY")
        default = SecurityFactsService().build("BIMAS", allow_sec_cache_replay=False)
        self.assertIsNone(default.return_3m)
        self.assertNotIn("fetch_thb_trading_date", FACTS.read_text(encoding="utf-8"))
        self.assertNotIn("download_thb_zip", FACTS.read_text(encoding="utf-8"))
        self.assertNotIn("DEFAULT_CACHE_DIR", FACTS.read_text(encoding="utf-8"))
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertNotIn("8e_enabled", ENGINE.read_text(encoding="utf-8"))
        self.assertIn('("return_3m", scale(facts.return_3m, -20, 20), 0.35)', SI.read_text(encoding="utf-8"))
        self.assertEqual(DEFAULT_CACHE_DIR, Path(".cache/bist_thb_history"))
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        view = evaluate_security_intelligence(
            SecurityFactsService().build(
                "BIMAS",
                kap_financials=kap_security_facts_payload(
                    ingest_public_kap_financials(
                        parse_public_kap_html(
                            bimas_tam_tl_eps_html(),
                            symbol="BIMAS",
                            disclosure_id="1570150",
                            cached=True,
                        )
                    )
                ),
                bist_price_history=weekday_series("BIMAS", end=END, calendar_days=400, start_price=400.0),
                allow_sec_cache_replay=False,
            )
        )
        self.assertNotEqual(view.momentum.status, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
