from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_si_readiness import audit_bist_si_readiness
from services.kap_annual_history import (
    AUTHORITATIVE_CURRENT,
    BLOCKED,
    COMPARATIVE_EVIDENCE,
    READY,
    RESTATED,
    STATUS_FOUND,
    build_kap_annual_history,
    cagr,
    comparable_field_series,
    growth_readiness,
    kap_security_facts_payload_from_history,
    safe_growth_fields,
    yoy_growth,
)
from services.kap_financial_bridge import KapIdentityError
from services.kap_public_contract import SOURCE_UNAVAILABLE, public_detailed_search_url
from services.kap_public_fr_discovery import (
    annual_fr_discoveries,
    classify_kap_period_label,
    discoveries_for_years,
    incremental_annual_targets,
    parse_detailed_search_payload,
    parse_fr_disclosure_index,
)
from services.kap_public_parser import parse_public_kap_html
from services.kap_public_source import KapPublicFinancialSource, KapPublicSourceError
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_annual_pilot import CAPTURED_ANNUAL_FR_IDS
from tests.fixtures.kap_detailed_search import (
    AUTHORITATIVE_REVENUE_TRY,
    FIXTURE_DISCLAIMER,
    detailed_search_json,
    official_fy_docs_html,
    official_fy_html,
    one_year_window_search_html,
)
from tests.fixtures.kap_eps_fy_rows import asels_unresolved_eps_html


DISCOVERY = Path("services/kap_public_fr_discovery.py")
SOURCE = Path("services/kap_public_source.py")
FACTS = Path("services/security_facts_service.py")
MOMENTUM = Path("services/bist_momentum_facts.py")
MARKET = Path("services/bist_official_market_facts.py")
PARTICIPATION = Path("services/bist_official_participation_policy.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
SI_FIREWALL = Path("services/security_intelligence_contract.py")


def _doc(html: str, *, symbol: str, disclosure_id: str):
    return parse_public_kap_html(
        html,
        symbol=symbol,
        disclosure_id=disclosure_id,
        include_comparative=True,
    )


def _official_docs(symbol: str):
    return [
        _doc(html, symbol=symbol, disclosure_id=nid)
        for nid, html in official_fy_docs_html(symbol).items()
    ]


class DetailedSearchDiscoveryTests(unittest.TestCase):
    def test_historical_years_beyond_default_one_year_window(self) -> None:
        rows = parse_detailed_search_payload(detailed_search_json())
        annual = annual_fr_discoveries(rows)
        years = {(row.symbol, int(row.year)) for row in annual}
        self.assertIn(("BIMAS", 2022), years)
        self.assertIn(("BIMAS", 2023), years)
        self.assertIn(("TUPRS", 2022), years)
        self.assertIn(("TUPRS", 2023), years)
        self.assertTrue(all(row.period == "FY" for row in annual))
        self.assertNotIn("1478794", {row.notification_id for row in annual})
        self.assertNotIn("9990001", {row.notification_id for row in annual})

    def test_period_codes_and_no_ytd_contamination(self) -> None:
        self.assertEqual(classify_kap_period_label("4"), "FY")
        self.assertEqual(classify_kap_period_label(4), "FY")
        self.assertEqual(classify_kap_period_label("2"), "YTD")
        self.assertEqual(classify_kap_period_label("1"), "Q")
        default_window = parse_fr_disclosure_index(one_year_window_search_html())
        default_years = {int(row.year) for row in annual_fr_discoveries(default_window)}
        self.assertNotIn(2022, default_years)
        detailed_years = {
            int(row.year)
            for row in annual_fr_discoveries(parse_detailed_search_payload(detailed_search_json()))
            if row.symbol == "BIMAS"
        }
        self.assertTrue({2022, 2023, 2024, 2025}.issubset(detailed_years))

    def test_direct_notification_ids_are_discovered(self) -> None:
        by_year = discoveries_for_years(
            parse_detailed_search_payload(detailed_search_json()),
            (2022, 2023, 2024, 2025),
        )
        # Mixed-symbol payload: latest submission per year is TUPRS then BIMAS
        # depending on date. Check symbol-specific rows instead.
        rows = annual_fr_discoveries(parse_detailed_search_payload(detailed_search_json()))
        bimas = {int(row.year): row.notification_id for row in rows if row.symbol == "BIMAS"}
        tuprs = {int(row.year): row.notification_id for row in rows if row.symbol == "TUPRS"}
        self.assertEqual(bimas[2022], CAPTURED_ANNUAL_FR_IDS["BIMAS"][2022])
        self.assertEqual(bimas[2023], CAPTURED_ANNUAL_FR_IDS["BIMAS"][2023])
        self.assertEqual(tuprs[2022], CAPTURED_ANNUAL_FR_IDS["TUPRS"][2022])
        self.assertEqual(tuprs[2023], CAPTURED_ANNUAL_FR_IDS["TUPRS"][2023])
        self.assertIsNotNone(by_year[2022])
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)


class OfficialHistoryTests(unittest.TestCase):
    def test_bimas_and_tuprs_2022_2023_comparable(self) -> None:
        for symbol in ("BIMAS", "TUPRS"):
            history = build_kap_annual_history(symbol, _official_docs(symbol))
            self.assertEqual(history.reporting_basis, "CONSOLIDATED")
            self.assertEqual(set(history.cell_status.values()), {STATUS_FOUND})
            years = [item.year for item in history.canonical_years()]
            self.assertEqual(years, [2022, 2023, 2024, 2025])
            revenue = dict(comparable_field_series(history, "revenue"))
            self.assertEqual(revenue, AUTHORITATIVE_REVENUE_TRY[symbol])
            self.assertEqual(len({item.year for item in history.canonical_years()}), 4)

    def test_direct_vs_comparative_and_restatement_precedence(self) -> None:
        bimas_2023 = _doc(
            official_fy_html("BIMAS", 2023),
            symbol="BIMAS",
            disclosure_id="1285893",
        )
        bimas_2022_direct = _doc(
            official_fy_html("BIMAS", 2022),
            symbol="BIMAS",
            disclosure_id="1124000",
        )
        history = build_kap_annual_history("BIMAS", [bimas_2022_direct, bimas_2023])
        year_2022 = next(item for item in history.years if item.year == 2022)
        year_2023 = next(item for item in history.years if item.year == 2023)
        self.assertEqual(year_2023.provenance, AUTHORITATIVE_CURRENT)
        self.assertEqual(year_2022.provenance, COMPARATIVE_EVIDENCE)
        self.assertEqual(year_2022.notification_id, "1285893")
        self.assertIn(RESTATED, history.warnings)
        self.assertEqual(year_2022.facts["revenue"], AUTHORITATIVE_REVENUE_TRY["BIMAS"][2022])

    def test_no_ttm_or_ytd_construction(self) -> None:
        source = Path("services/kap_annual_history.py").read_text(encoding="utf-8")
        self.assertIn("Does not invent FCF, ROIC, TTM", source)
        history = build_kap_annual_history("TUPRS", _official_docs("TUPRS"))
        self.assertTrue(all(item.period_end.endswith("12-31") for item in history.years))
        self.assertTrue(all(item.period_start.endswith("01-01") for item in history.years if item.period_start))


class GrowthAndFactsTests(unittest.TestCase):
    def test_revenue_yoy_and_cagr(self) -> None:
        history = build_kap_annual_history("BIMAS", _official_docs("BIMAS"))
        growth = safe_growth_fields(history)
        revenue = AUTHORITATIVE_REVENUE_TRY["BIMAS"]
        self.assertAlmostEqual(growth["revenue_growth_yoy"], yoy_growth(revenue[2025], revenue[2024]))
        self.assertAlmostEqual(growth["revenue_cagr_3y"], cagr(revenue[2025], revenue[2022], 3))
        ready = growth_readiness(history)
        self.assertEqual(ready["revenue_growth_yoy"], READY)
        self.assertEqual(ready["revenue_cagr_3y"], READY)
        self.assertEqual(ready["eps_growth_yoy"], BLOCKED)
        self.assertEqual(ready["eps_cagr_3y"], BLOCKED)
        self.assertEqual(ready["fcf_cagr_3y"], BLOCKED)

    def test_securityfacts_keeps_latest_fy_2025(self) -> None:
        history = build_kap_annual_history("TUPRS", _official_docs("TUPRS"))
        payload = kap_security_facts_payload_from_history(history)
        facts = SecurityFactsService().build(
            "TUPRS",
            kap_financials=payload,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.period_kind, "FY")
        self.assertEqual(str(facts.as_of)[:10], "2025-12-31")
        self.assertEqual(facts.revenue, AUTHORITATIVE_REVENUE_TRY["TUPRS"][2025])
        self.assertIsNotNone(facts.revenue_growth_yoy)
        self.assertIsNotNone(facts.revenue_cagr_3y)
        self.assertIsNone(facts.free_cash_flow)
        self.assertIsNone(facts.eps_cagr_3y)
        self.assertIsNone(facts.eps_growth_yoy)

    def test_asels_eps_and_momentum_and_market_cap_untouched(self) -> None:
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials={"period_kind": "FY"},
            allow_sec_cache_replay=False,
        )
        asels = _doc(asels_unresolved_eps_html(), symbol="ASELS", disclosure_id="1561039")
        from services.kap_public_bridge import ingest_public_kap_financials
        from services.kap_eps_normalization import BASIS_UNRESOLVED, asels_anomaly_classification

        payload = ingest_public_kap_financials(asels)
        blocked = SecurityFactsService().build(
            "ASELS",
            kap_financials=payload,
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(blocked.eps)
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)
        self.assertIsNone(facts.return_3m)
        momentum_src = MOMENTUM.read_text(encoding="utf-8")
        self.assertNotIn("kap_annual_history", momentum_src)
        self.assertNotIn("byCriteria", MARKET.read_text(encoding="utf-8"))
        self.assertNotIn("byCriteria", FACTS.read_text(encoding="utf-8"))


class IsolationAndSafetyTests(unittest.TestCase):
    def test_us_isolation_and_no_default_live_fetch(self) -> None:
        with self.assertRaises(KapIdentityError):
            build_kap_annual_history("AAPL", _official_docs("BIMAS"))
        with self.assertRaises(KapIdentityError):
            build_kap_annual_history("CRM", _official_docs("TUPRS"))
        source = KapPublicFinancialSource(allow_live=False, cache_dir=Path("/tmp/nabi-kap-hist-empty"))
        with self.assertRaises(KapPublicSourceError) as ctx:
            source.fetch_detailed_search(
                member_id="4028e4a140e95be70140ee1b7b030119",
                from_date="2022-01-01",
                to_date="2022-12-31",
            )
        self.assertEqual(str(ctx.exception), SOURCE_UNAVAILABLE)
        self.assertFalse(KapPublicFinancialSource().allow_live)
        parsed = source.discover_from_detailed_search(detailed_search_json())
        self.assertTrue(parsed)
        self.assertIn("/tr/api/disclosure/members/byCriteria", public_detailed_search_url())
        self.assertNotIn("NABI_KAP_API_KEY", SOURCE.read_text(encoding="utf-8"))
        self.assertNotIn("1561039", DISCOVERY.read_text(encoding="utf-8"))

    def test_participation_8e_and_no_persistence(self) -> None:
        self.assertNotIn("kap_annual_history", PARTICIPATION.read_text(encoding="utf-8"))
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, result.blocking_reasons)
        self.assertNotIn("BIST_SI_ENABLED", SI_FIREWALL.read_text(encoding="utf-8"))
        history = build_kap_annual_history("BIMAS", _official_docs("BIMAS"))
        facts = SecurityFactsService().build(
            "BIMAS",
            kap_financials=kap_security_facts_payload_from_history(history),
            allow_sec_cache_replay=False,
        )
        audit = audit_bist_si_readiness(facts, kap_bundle=history.latest().bundle)
        self.assertFalse(audit.persisted)
        view = SecurityIntelligenceService().evaluate(facts)
        self.assertIsNotNone(view.growth)
        known = {CAPTURED_ANNUAL_FR_IDS["BIMAS"][2025]}
        fresh = incremental_annual_targets(
            parse_detailed_search_payload(detailed_search_json()),
            known,
        )
        ids = {row.notification_id for row in fresh}
        self.assertIn("1124000", ids)
        self.assertNotIn("1570150", ids)
