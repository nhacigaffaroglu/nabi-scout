from __future__ import annotations

from pathlib import Path
import unittest


PAGE = Path("pages/14_Fon_Aday_Detayi.py")
COMPONENT = Path("components/turkiye_fund_candidate_detail_ui.py")
SERVICE = Path("services/turkiye_fund_candidate_detail.py")


class CandidateDetailPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.component = COMPONENT.read_text(encoding="utf-8")
        cls.service = SERVICE.read_text(encoding="utf-8")

    def test_page_uses_default_scanner_read(self):
        self.assertIn("load_default_scanner_result", self.page)
        self.assertNotIn("Supabase", self.page)
        self.assertNotIn("CandidateRepository", self.page)

    def test_page_links_to_existing_fund_report_only_through_safe_handoff(self):
        self.assertIn("is_turkiye_fund_nav_identity", self.page)
        self.assertIn("apply_turkiye_fund_report_handoff", self.page)
        self.assertIn('st.switch_page("pages/9_Fund_Report.py")', self.page)

    def test_no_execution_or_allocation_actions(self):
        combined = "\n".join((self.page, self.component, self.service))
        for forbidden in (
            "place_order",
            "execute_trade",
            "target_weight",
            "position_size",
            "portfolio_write",
            "new_money_execute",
            "eight_e_execute",
            "--persist",
        ):
            self.assertNotIn(forbidden, combined)

    def test_ui_displays_provenance_and_firewall(self):
        self.assertIn("Scanner veri tarihi", self.component)
        self.assertIn("Hesaplama tarihi", self.component)
        self.assertIn("Sıralama kuralı", self.component)
        self.assertIn("Araştırma güvenlik sınırları", self.component)

    def test_final_user_facing_copy_is_turkish(self):
        self.assertIn("İnceleme gerekli", self.component)
        self.assertIn("Katılım açısından uygun", self.component)
        self.assertIn("Scanner değerlendirmesine uygun", self.component)
        self.assertIn("Geçerli sayısal FI skoru", self.component)
        self.assertIn("Teknik kanıt kodları", self.component)

    def test_final_page_hides_production_jargon(self):
        self.assertIn(
            "Bu fon için standart Fon Raporu bağlantısı henüz etkin değil.",
            self.page,
        )
        self.assertNotIn(
            "Canonical production Fon Raporu",
            self.page,
        )

    def test_scanner_links_to_candidate_detail_without_promoting_it_to_primary_nav(self):
        scanner_page = Path("pages/13_Turkiye_Fon_Tarama.py").read_text(encoding="utf-8")
        ui_source = Path("services/ui.py").read_text(encoding="utf-8")

        self.assertIn('st.button("Aday Detayını Aç"', scanner_page)
        self.assertIn(
            'st.session_state["turkiye_fund_candidate_detail_code"] = selected',
            scanner_page,
        )
        self.assertIn(
            'st.query_params["candidate_fund"] = selected',
            scanner_page,
        )
        self.assertIn(
            'st.switch_page("pages/14_Fon_Aday_Detayi.py")',
            scanner_page,
        )

        self.assertNotIn(
            '("pages/14_Fon_Aday_Detayi.py", "Fon Aday Detayı", "🔎")',
            ui_source,
        )


    def test_service_declares_no_authority(self):
        self.assertIn("execution_authority: bool = False", self.service)
        self.assertIn("production_persist: bool = False", self.service)
        self.assertIn("threshold_locked: bool = False", self.service)
        self.assertIn("recommendation_band_applied: bool = False", self.service)


if __name__ == "__main__":
    unittest.main()
