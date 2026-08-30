from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_si_readiness import (
    SI_EVALUATION_BLOCKED_BY_READINESS,
    audit_bist_si_readiness,
    kap_payload_is_si_eligible,
)
from services.kap_annual_history import (
    AVAILABLE_CANONICAL,
    AVAILABLE_RAW_ONLY,
    BLOCKED,
    COMPARABILITY_BREAK,
    METHODOLOGY_UNRESOLVED,
    NOT_AVAILABLE,
    READY,
    RESTATEMENT_AMBIGUOUS,
    RESTATED,
    STATUS_FOUND,
    STATUS_INCOMPATIBLE,
    build_kap_annual_history,
    cagr,
    comparable_field_series,
    growth_readiness,
    inventory_annual_facts,
    kap_security_facts_payload_from_history,
    quality_readiness,
    safe_growth_fields,
    yoy_growth,
)
from services.kap_financial_bridge import KapIdentityError, kap_security_facts_payload
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_fr_discovery import (
    annual_fr_discoveries,
    classify_kap_period_label,
    incremental_annual_targets,
    parse_fr_disclosure_index,
)
from services.kap_public_parser import parse_public_kap_html
from services.kap_public_source import KapPublicFinancialSource
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_annual_pilot import (
    CAPTURED_ANNUAL_FR_IDS,
    FIXTURE_DISCLAIMER,
    annual_series_html,
    checkbox_only_search_html,
    fr_search_html,
    fy_html,
    restated_prior_html,
    standalone_2022_html,
)
from tests.fixtures.kap_public_pilot import compact_public_html, fy_public_html


DISCOVERY = Path("services/kap_public_fr_discovery.py")
HISTORY = Path("services/kap_annual_history.py")
SOURCE = Path("services/kap_public_source.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
SI_FIREWALL = Path("services/security_intelligence_contract.py")
PARTICIPATION_POLICY = Path("services/bist_official_participation_policy.py")


def _doc(html: str, *, symbol: str = "ASELS", disclosure_id: str, include_comparative: bool = True):
    return parse_public_kap_html(
        html,
        symbol=symbol,
        disclosure_id=disclosure_id,
        include_comparative=include_comparative,
    )


def _series_docs(symbol: str = "ASELS"):
    mapping = {
        2022: "1117839",
        2023: "1262825",
        2024: "1395801",
        2025: "1561039",
    }
    return [
        _doc(html, symbol=symbol, disclosure_id=mapping[year])
        for year, html in annual_series_html().items()
    ]


class AnnualDiscoveryTests(unittest.TestCase):
    def test_annual_fr_discovery(self) -> None:
        escaped = fr_search_html().replace('"', r'\"')
        rows = parse_fr_disclosure_index(escaped)
        annual = annual_fr_discoveries(rows)
        ids = {row.notification_id for row in annual}
        self.assertIn("1561039", ids)
        self.assertIn("1395801", ids)
        self.assertIn("1262825", ids)
        self.assertIn("1117839", ids)
        self.assertNotIn("1643141", ids)
        self.assertNotIn("1598316", ids)
        self.assertNotIn("1561038", ids)
        asels_2025 = next(row for row in annual if row.year == "2025")
        self.assertEqual(asels_2025.period, "FY")
        self.assertEqual(asels_2025.symbol, "ASELS")
        self.assertTrue(asels_2025.source_url.endswith("/Bildirim/1561039"))

    def test_fy_period_identification(self) -> None:
        self.assertEqual(classify_kap_period_label("Yıllık"), "FY")
        self.assertEqual(classify_kap_period_label("6 Aylık"), "YTD")
        self.assertEqual(classify_kap_period_label("9 Aylık"), "YTD")
        self.assertEqual(classify_kap_period_label("3 Aylık"), "Q")

    def test_checkbox_fallback_and_no_hardcoded_ids(self) -> None:
        rows = parse_fr_disclosure_index(checkbox_only_search_html())
        annual = annual_fr_discoveries(rows)
        self.assertEqual([row.notification_id for row in annual], ["2001"])
        source = DISCOVERY.read_text(encoding="utf-8")
        self.assertNotIn("1561039", source)
        self.assertNotIn("ASELS", source)
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertEqual(CAPTURED_ANNUAL_FR_IDS["ASELS"][2025], "1561039")


class PeriodGateTests(unittest.TestCase):
    def test_ytd_rejected_from_fy_path(self) -> None:
        ytd = _doc(compact_public_html(), disclosure_id="1643141", include_comparative=False)
        history = build_kap_annual_history("ASELS", [ytd], target_years=(2026,))
        self.assertTrue(any(item["reason"] == "REJECTED_NON_FY" for item in history.rejected))
        self.assertEqual(history.cell_status.get(2026), "NOT_FOUND")
        payload = kap_security_facts_payload(ingest_public_kap_financials(ytd))
        self.assertFalse(kap_payload_is_si_eligible(payload))
        self.assertIsNone(payload.get("revenue"))

    def test_q_rejected_from_fy_path(self) -> None:
        q_only = compact_public_html(
            include_quarter=True,
            is_current="Cari Dönem 3 Aylık 01.04.2026 - 30.06.2026",
            is_prior="Önceki Dönem 3 Aylık 01.04.2025 - 30.06.2025",
        )
        doc = _doc(q_only, disclosure_id="1598316")
        history = build_kap_annual_history("ASELS", [doc], target_years=(2026,))
        self.assertTrue(any(item["reason"] == "REJECTED_NON_FY" for item in history.rejected))
        self.assertTrue(all(item["period_kind"] != "FY" for item in history.rejected))

    def test_2026_6_ytd_still_excluded(self) -> None:
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=ingest_public_kap_financials(
                _doc(compact_public_html(), disclosure_id="1643141", include_comparative=False)
            ),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.revenue)
        self.assertNotEqual(facts.period_kind, "FY")


class ConsolidationAndRestatementTests(unittest.TestCase):
    def test_consolidated_history_consistency(self) -> None:
        history = build_kap_annual_history("ASELS", _series_docs())
        self.assertEqual(history.reporting_basis, "CONSOLIDATED")
        self.assertEqual(set(history.cell_status.values()), {STATUS_FOUND})
        self.assertEqual([item.year for item in history.canonical_years()], [2022, 2023, 2024, 2025])

    def test_standalone_consolidated_comparability_break(self) -> None:
        docs = _series_docs()
        docs[0] = _doc(standalone_2022_html(), disclosure_id="1117839")
        history = build_kap_annual_history("ASELS", docs)
        self.assertEqual(history.cell_status[2022], STATUS_INCOMPATIBLE)
        self.assertTrue(any(item["status"] == COMPARABILITY_BREAK for item in history.comparability_breaks))
        years = [year for year, _ in comparable_field_series(history, "revenue")]
        self.assertNotIn(2022, years)
        self.assertEqual(growth_readiness(history)["revenue_cagr_3y"], BLOCKED)

    def test_current_prior_column_and_duplicate_period(self) -> None:
        current_2024 = _doc(
            fy_html(year=2024, revenue="121.000.000", profit="14.000.000"),
            disclosure_id="1395801",
        )
        later = _doc(restated_prior_html(), disclosure_id="1561039")
        history = build_kap_annual_history("ASELS", [current_2024, later], target_years=(2024, 2025))
        year_2024 = history.year_map()[2024]
        self.assertEqual(year_2024.facts["revenue"], 125_000_000_000.0)
        self.assertEqual(year_2024.notification_id, "1561039")
        self.assertTrue(any(item["status"] == RESTATED for item in history.restatements))

    def test_restatement_ambiguous_keeps_both(self) -> None:
        first = _doc(
            fy_html(year=2025, revenue="100.000.000", profit="10.000.000", submitted="24.02.2026 18:00:00"),
            disclosure_id="1561039",
        )
        second = _doc(
            fy_html(year=2025, revenue="110.000.000", profit="11.000.000", submitted="24.02.2026 18:00:00"),
            disclosure_id="1561041",
        )
        history = build_kap_annual_history("ASELS", [first, second], target_years=(2025,))
        self.assertIn(RESTATEMENT_AMBIGUOUS, history.warnings)
        self.assertEqual(len([item for item in history.evidence if item.year == 2025 and item.column == "CURRENT"]), 2)


class NormalizationAndFactsTests(unittest.TestCase):
    def test_zero_taxonomy_row_does_not_overwrite_net_income(self) -> None:
        html = fy_html(year=2025, revenue="133.100.000", profit="16.000.000")
        html = html.replace(
            "</table>\n</html>",
            (
                '<tr class="data-input-row">'
                '<td class="taxonomy-field-name-cell">'
                '<div class="gwt-Label taxonomy-field-name">ifrs-full_ProfitLoss|</div></td>'
                '<td class="taxonomy-field-title">'
                '<div class="gwt-Label multi-language-content content-tr">Dönem Karı</div></td>'
                '<td class="taxonomy-context-value">0</td>'
                '<td class="taxonomy-context-value">0</td></tr></table>\n</html>'
            ),
        )
        history = build_kap_annual_history(
            "ASELS",
            [_doc(html, disclosure_id="1561039")],
            target_years=(2025,),
        )
        self.assertEqual(history.latest().facts["net_income"], 16_000_000_000.0)

    def test_annual_normalization_and_scale(self) -> None:
        doc = _doc(fy_html(year=2025, revenue="133.100.000", profit="16.000.000"), disclosure_id="1561039")
        bundle = ingest_public_kap_financials(doc)
        self.assertEqual(bundle.fact("revenue").normalized_value, 133_100_000_000.0)
        self.assertEqual(bundle.fact("revenue").raw_unit_scale, 1000)
        self.assertEqual(bundle.fact("revenue").currency, "TRY")

    def test_fy_existing_securityfacts_path(self) -> None:
        history = build_kap_annual_history("ASELS", _series_docs())
        payload = kap_security_facts_payload_from_history(history)
        self.assertTrue(kap_payload_is_si_eligible(payload))
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=payload,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.period_kind, "FY")
        self.assertEqual(facts.revenue, 133_100_000_000.0)
        self.assertEqual(facts.net_income, 16_000_000_000.0)
        self.assertIsNotNone(facts.revenue_growth_yoy)
        self.assertIsNotNone(facts.revenue_cagr_3y)
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.free_cash_flow)
        self.assertIsNone(facts.roic)

    def test_annual_revenue_and_net_income_history(self) -> None:
        history = build_kap_annual_history("BIMAS", _series_docs("BIMAS"))
        revenue = dict(history.series("revenue"))
        income = dict(history.series("net_income"))
        self.assertEqual(revenue[2022], 100_000_000_000.0)
        self.assertEqual(revenue[2025], 133_100_000_000.0)
        self.assertEqual(income[2025], 16_000_000_000.0)

    def test_safe_yoy_and_cagr(self) -> None:
        history = build_kap_annual_history("TUPRS", _series_docs("TUPRS"))
        growth = safe_growth_fields(history)
        self.assertAlmostEqual(growth["revenue_growth_yoy"], yoy_growth(133_100_000_000.0, 121_000_000_000.0))
        self.assertAlmostEqual(growth["revenue_cagr_3y"], cagr(133_100_000_000.0, 100_000_000_000.0, 3))
        self.assertEqual(growth_readiness(history)["revenue_growth_yoy"], READY)
        self.assertEqual(growth_readiness(history)["revenue_cagr_3y"], READY)
        self.assertEqual(growth_readiness(history)["eps_growth_yoy"], BLOCKED)
        self.assertEqual(growth_readiness(history)["fcf_cagr_3y"], BLOCKED)

    def test_no_invented_eps_fcf_roic_or_debt(self) -> None:
        history = build_kap_annual_history("ASELS", _series_docs())
        inventory = inventory_annual_facts(history, observed_concepts=("ifrs-full_GrossProfit",))
        self.assertEqual(inventory["revenue"], AVAILABLE_CANONICAL)
        self.assertEqual(inventory["gross_profit"], AVAILABLE_RAW_ONLY)
        self.assertEqual(inventory["fcf"], METHODOLOGY_UNRESOLVED)
        self.assertEqual(inventory["roic"], NOT_AVAILABLE)
        self.assertEqual(inventory["debt"], NOT_AVAILABLE)
        self.assertEqual(inventory["eps"], NOT_AVAILABLE)
        source = HISTORY.read_text(encoding="utf-8")
        self.assertNotIn("total_liabilities", source.casefold())
        self.assertNotIn("interest_bearing_debt =", source)
        quality = quality_readiness(history)
        self.assertEqual(quality["ROE"], READY)
        self.assertEqual(quality["ROA"], READY)
        self.assertEqual(quality["current_ratio"], READY)
        self.assertEqual(quality["debt_to_equity"], BLOCKED)
        self.assertEqual(quality["net_debt_to_fcf"], BLOCKED)
        self.assertEqual(quality["ROIC"], "NOT_USED")


class IsolationAndSafetyTests(unittest.TestCase):
    def test_us_isolation(self) -> None:
        docs = _series_docs()
        with self.assertRaises(KapIdentityError):
            build_kap_annual_history("AAPL", docs)
        with self.assertRaises(KapIdentityError):
            build_kap_annual_history("CRM", docs)
        aapl = SecurityFactsService().build("AAPL", kap_financials={"revenue": 1}, allow_sec_cache_replay=False)
        self.assertIsNone(aapl.revenue)

    def test_participation_and_8e_unchanged(self) -> None:
        policy = PARTICIPATION_POLICY.read_text(encoding="utf-8")
        self.assertNotIn("kap_annual_history", policy)
        self.assertNotIn("BistAnnualScoringEngine", policy)
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
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertIn("BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("BIST_SI_ENABLED", SI_FIREWALL.read_text(encoding="utf-8"))

    def test_no_si_persistence_and_no_paid_api(self) -> None:
        history = build_kap_annual_history("ASELS", _series_docs())
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload_from_history(history),
            allow_sec_cache_replay=False,
        )
        audit = audit_bist_si_readiness(facts, kap_bundle=history.latest().bundle)
        self.assertFalse(audit.persisted)
        view = SecurityIntelligenceService().evaluate(facts)
        self.assertIsNotNone(view.overall_score)
        self.assertFalse(hasattr(view, "persisted") and getattr(view, "persisted"))
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("api_key", source)
        self.assertNotIn("NABI_KAP_API_KEY", source)

    def test_incremental_refresh_skips_known_notification(self) -> None:
        rows = annual_fr_discoveries(parse_fr_disclosure_index(fr_search_html()))
        known = {"1561039", "1395801", "1262825"}
        fresh = incremental_annual_targets(rows, known)
        ids = {row.notification_id for row in fresh}
        self.assertIn("1117839", ids)
        self.assertNotIn("1561039", ids)
        source = KapPublicFinancialSource(allow_live=False, cache_dir=Path("/tmp/nabi-kap-annual-empty"))
        discovered = source.discover_from_search_html(fr_search_html())
        self.assertTrue(all(row.period == "FY" for row in discovered))


class ShadowSiReadinessTests(unittest.TestCase):
    def test_shadow_only_not_production_ready(self) -> None:
        history = build_kap_annual_history("ASELS", _series_docs())
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=kap_security_facts_payload_from_history(history),
            allow_sec_cache_replay=False,
        )
        view = SecurityIntelligenceService().evaluate(facts)
        scored = sum(
            1
            for name in ("quality", "growth", "profitability", "balance_sheet", "valuation")
            if getattr(view, name).score is not None
        )
        self.assertGreaterEqual(scored, 3)
        self.assertIsNotNone(view.overall_score)
        self.assertIn("kap_normalized", facts.source)
        ytd_audit = audit_bist_si_readiness(
            SecurityFactsService().build(
                "ASELS",
                kap_financials=ingest_public_kap_financials(
                    _doc(compact_public_html(), disclosure_id="1643141", include_comparative=False)
                ),
                allow_sec_cache_replay=False,
            )
        )
        self.assertEqual(ytd_audit.readiness_block, SI_EVALUATION_BLOCKED_BY_READINESS)


if __name__ == "__main__":
    unittest.main()
