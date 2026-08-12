import py_compile
import unittest


class EquitySurfacePageSmokeTests(unittest.TestCase):
    def test_company_report_guard_present(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("enrich_candidate_classification_from_db", source)
        self.assertIn("is_equity_candidate_surface_eligible", source)
        self.assertIn("build_company_intelligence", source)
        self.assertIn("build_company_report_participation", source)
        self.assertIn("render_company_report_participation_section", source)
        enrich_index = source.index("enrich_candidate_classification_from_db")
        guard_index = source.index("if not is_equity_candidate_surface_eligible(candidate):")
        intelligence_index = source.index("intelligence = build_company_intelligence(")
        self.assertLess(enrich_index, guard_index)
        self.assertLess(guard_index, intelligence_index)

    def test_aday_havuzu_firewall_present(self) -> None:
        with open("pages/2_Aday_Havuzu.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("filter_equity_candidate_surface", source)
        self.assertNotIn('"Tümü", "Hisse", "ETF"', source)

    def test_research_monitor_firewall_present(self) -> None:
        with open("pages/3_Research_Monitor.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("filter_equity_candidate_surface", source)

    def test_pages_compile(self) -> None:
        for path in (
            "pages/1_Dashboard.py",
            "pages/2_Aday_Havuzu.py",
            "pages/3_Research_Monitor.py",
            "pages/4_Company_Report.py",
            "pages/9_Fund_Report.py",
        ):
            py_compile.compile(path, doraise=True)


if __name__ == "__main__":
    unittest.main()
