import unittest

from services.candidate_surface_service import (
    enrich_candidate_classification,
    enrich_candidate_classification_from_db,
    filter_equity_candidate_surface,
    is_equity_candidate_surface_eligible,
)


class CandidateSurfaceEligibilityTests(unittest.TestCase):
    def test_nvda_equity_eligible(self) -> None:
        self.assertTrue(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "NVDA",
                    "asset_type": "Hisse",
                    "security_type": "COMMON_STOCK",
                    "issuer_category": "OPERATING_COMPANY",
                    "is_etf": False,
                }
            )
        )

    def test_legacy_etf_asset_type_blocked(self) -> None:
        self.assertFalse(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "SPUS",
                    "asset_type": "ETF",
                    "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
                }
            )
        )

    def test_is_etf_flag_blocked(self) -> None:
        self.assertFalse(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "QQQ",
                    "asset_type": "Hisse",
                    "is_etf": True,
                }
            )
        )

    def test_issuer_category_fund_blocked(self) -> None:
        self.assertFalse(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "HLAL",
                    "issuer_category": "FUND",
                }
            )
        )

    def test_security_type_etf_blocked(self) -> None:
        self.assertFalse(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "SPSK",
                    "security_type": "ETF",
                }
            )
        )

    def test_unknown_metadata_remains_eligible(self) -> None:
        self.assertTrue(
            is_equity_candidate_surface_eligible(
                {
                    "symbol": "MSFT",
                    "decision": "VERİ EKSİK",
                }
            )
        )

    def test_filter_equity_candidate_surface(self) -> None:
        rows = [
            {"symbol": "NVDA", "asset_type": "Hisse"},
            {"symbol": "SPUS", "asset_type": "ETF"},
        ]
        filtered = filter_equity_candidate_surface(rows)
        self.assertEqual([row["symbol"] for row in filtered], ["NVDA"])


class CandidateClassificationEnrichmentTests(unittest.TestCase):
    def test_sparse_spus_session_blocked_after_db_backfill(self) -> None:
        session = {"symbol": "SPUS", "company_name": "SPUS"}
        persisted = {
            "symbol": "SPUS",
            "asset_type": "ETF",
            "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
        }
        enriched = enrich_candidate_classification(session, persisted)
        self.assertFalse(is_equity_candidate_surface_eligible(enriched))

    def test_sparse_hlal_spsk_blocked_after_db_backfill(self) -> None:
        for symbol in ("HLAL", "SPSK"):
            with self.subTest(symbol=symbol):
                session = {"symbol": symbol, "company_name": symbol}
                persisted = {"symbol": symbol, "asset_type": "ETF"}
                enriched = enrich_candidate_classification(session, persisted)
                self.assertFalse(is_equity_candidate_surface_eligible(enriched))

    def test_sparse_nvda_allowed_after_db_backfill(self) -> None:
        session = {"symbol": "NVDA", "company_name": "NVIDIA"}
        persisted = {
            "symbol": "NVDA",
            "asset_type": "Hisse",
            "security_type": "COMMON_STOCK",
            "issuer_category": "OPERATING_COMPANY",
            "is_etf": False,
        }
        enriched = enrich_candidate_classification(session, persisted)
        self.assertTrue(is_equity_candidate_surface_eligible(enriched))
        self.assertEqual(enriched["company_name"], "NVIDIA")

    def test_full_etf_session_still_blocked(self) -> None:
        session = {
            "symbol": "SPUS",
            "asset_type": "ETF",
            "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
        }
        self.assertFalse(is_equity_candidate_surface_eligible(session))

    def test_query_param_etf_row_still_blocked(self) -> None:
        persisted = {
            "symbol": "SPUS",
            "asset_type": "ETF",
            "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
        }
        self.assertFalse(is_equity_candidate_surface_eligible(persisted))

    def test_enrichment_preserves_session_display_fields(self) -> None:
        session = {"symbol": "SPUS", "company_name": "Session Label"}
        persisted = {
            "symbol": "SPUS",
            "asset_type": "ETF",
            "company_name": "DB Label",
        }
        enriched = enrich_candidate_classification(session, persisted)
        self.assertEqual(enriched["company_name"], "Session Label")
        self.assertEqual(enriched["asset_type"], "ETF")

    def test_no_db_row_preserves_unknown_metadata(self) -> None:
        session = {"symbol": "SPUS", "company_name": "SPUS"}
        enriched = enrich_candidate_classification_from_db(
            session,
            get_by_symbol=lambda _symbol: None,
        )
        self.assertTrue(is_equity_candidate_surface_eligible(enriched))

    def test_enrichment_db_read_only(self) -> None:
        calls = []

        def get_by_symbol(symbol: str):
            calls.append(symbol)
            return {"symbol": symbol, "asset_type": "ETF"}

        enrich_candidate_classification_from_db(
            {"symbol": "SPUS", "company_name": "SPUS"},
            get_by_symbol,
        )
        self.assertEqual(calls, ["SPUS"])

    def test_complete_classification_skips_db_lookup(self) -> None:
        calls = []

        enrich_candidate_classification_from_db(
            {
                "symbol": "NVDA",
                "asset_type": "Hisse",
                "security_type": "COMMON_STOCK",
                "issuer_category": "OPERATING_COMPANY",
                "is_etf": False,
            },
            lambda symbol: calls.append(symbol) or {},
        )
        self.assertEqual(calls, [])


class CompanyReportSparseSessionGuardTests(unittest.TestCase):
    def test_company_report_enriches_before_guard(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        enrich_index = source.index("enrich_candidate_classification_from_db")
        guard_index = source.index("if not is_equity_candidate_surface_eligible(candidate):")
        intelligence_index = source.index("intelligence = build_company_intelligence(")
        self.assertLess(enrich_index, guard_index)
        self.assertLess(guard_index, intelligence_index)

    def test_build_company_intelligence_not_reachable_for_sparse_etf(self) -> None:
        session = {"symbol": "SPUS", "company_name": "SPUS"}
        persisted = {"symbol": "SPUS", "asset_type": "ETF"}
        enriched = enrich_candidate_classification(session, persisted)
        self.assertFalse(is_equity_candidate_surface_eligible(enriched))


if __name__ == "__main__":
    unittest.main()
