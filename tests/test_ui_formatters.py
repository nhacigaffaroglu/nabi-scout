import py_compile
import unittest
from pathlib import Path

from services.ui_formatters import (
    LEGACY_HISTORY_NOTE,
    format_badge,
    format_badges_compact,
    format_change_window_summary,
    format_data_quality_notes,
    format_date_dmy,
    format_date_tr,
    format_datetime_tr,
    format_priority_reason,
    format_priority_reasons,
    parse_date_dmy,
)


class UiFormatterBadgeTests(unittest.TestCase):
    def test_new_badge_mapping(self) -> None:
        self.assertEqual(format_badge("NEW"), "🆕 Yeni")

    def test_legacy_history_mapping(self) -> None:
        self.assertEqual(format_badge("LEGACY_HISTORY"), "🕘 Sınırlı geçmiş veri")

    def test_data_issue_mapping(self) -> None:
        self.assertEqual(format_badge("DATA_ISSUE"), "⚠️ Veri sorunu")

    def test_stale_aging_mapping(self) -> None:
        self.assertEqual(format_badge("STALE"), "🕒 Güncelliğini yitirmiş veri")
        self.assertEqual(format_badge("AGING"), "⏳ Eskiyen veri")

    def test_badges_compact(self) -> None:
        rendered = format_badges_compact(["NEW", "LEGACY_HISTORY"])
        self.assertIn("🆕 Yeni", rendered)
        self.assertIn("🕘 Sınırlı geçmiş veri", rendered)
        self.assertIn(" · ", rendered)


class UiFormatterDatetimeTests(unittest.TestCase):
    def test_valid_iso_datetime(self) -> None:
        rendered = format_datetime_tr("2026-08-10T20:08:43.393002+00:00")
        self.assertEqual(rendered, "10 Ağu 2026 · 20:08 UTC")

    def test_valid_iso_date_only(self) -> None:
        rendered = format_date_tr("2026-08-10T20:08:43+00:00")
        self.assertEqual(rendered, "10 Ağu 2026")

    def test_none_datetime(self) -> None:
        self.assertEqual(format_datetime_tr(None), "—")
        self.assertEqual(format_date_tr(None), "—")

    def test_invalid_datetime_safe_fallback(self) -> None:
        self.assertEqual(format_datetime_tr("not-a-date"), "not-a-date")
        self.assertEqual(format_date_tr(""), "—")


class UiFormatterNumericTurkishDateTests(unittest.TestCase):
    def test_iso_date_to_dmy(self) -> None:
        self.assertEqual(format_date_dmy("2025-08-07"), "07.08.2025")
        self.assertEqual(format_date_dmy("2025-05-14"), "14.05.2025")

    def test_iso_datetime_to_dmy(self) -> None:
        self.assertEqual(
            format_date_dmy("2025-05-14T00:00:00+00:00"),
            "14.05.2025",
        )

    def test_date_object_to_dmy(self) -> None:
        from datetime import date

        value = date(2025, 8, 7)
        self.assertEqual(format_date_dmy(value), "07.08.2025")
        self.assertEqual(value.isoformat(), "2025-08-07")

    def test_none_and_empty(self) -> None:
        self.assertEqual(format_date_dmy(None), "—")
        self.assertEqual(format_date_dmy(""), "—")

    def test_parse_dmy_roundtrip_storage_iso(self) -> None:
        parsed = parse_date_dmy("07.08.2025")
        self.assertEqual(parsed.isoformat(), "2025-08-07")
        self.assertEqual(format_date_dmy(parsed), "07.08.2025")
        self.assertIsNone(parse_date_dmy(""))
        self.assertIsNone(parse_date_dmy(None))
        with self.assertRaises(ValueError):
            parse_date_dmy("08/07/2025")
        with self.assertRaises(ValueError):
            parse_date_dmy("2025-08-07")

    def test_does_not_emit_us_format(self) -> None:
        rendered = format_date_dmy("2025-08-07")
        self.assertNotIn("/", rendered)
        self.assertNotEqual(rendered, "08/07/2025")
        self.assertNotEqual(rendered, "2025-08-07")

    def test_management_date_input_turkish(self) -> None:
        source = Path("components/portfolio_management_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Alış tarihi (opsiyonel)", source)
        self.assertIn("DATE_DMY_PLACEHOLDER", source)
        self.assertIn("parse_date_dmy", source)
        self.assertIn(".isoformat()", source)
        self.assertNotIn("st.date_input", source)
        self.assertNotIn("MM/DD/YYYY", source)

    def test_changed_surfaces_use_dmy_helper(self) -> None:
        files = [
            "pages/10_Wealth.py",
            "components/portfolio_advanced_ui.py",
            "components/portfolio_wave3_ui.py",
            "components/portfolio_management_ui.py",
        ]
        for path in files:
            source = Path(path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("MM/DD/YYYY", source)
                self.assertNotIn("%m/%d/%Y", source)
                self.assertIn("format_date_dmy", source)


class UiFormatterChangeCountTests(unittest.TestCase):
    def test_two_pairs_one_visible_event(self) -> None:
        events = [{"message": "Tek görünür event"}]
        summary = format_change_window_summary(15, events)
        self.assertEqual(summary, "Pencere değişim skoru: 15 · 1 önemli değişiklik")

    def test_zero_visible_events(self) -> None:
        self.assertEqual(format_change_window_summary(15, []), "Anlamlı değişiklik yok")

    def test_pluralization(self) -> None:
        events = [{"message": "A"}, {"message": "B"}]
        summary = format_change_window_summary(20, events)
        self.assertEqual(summary, "Pencere değişim skoru: 20 · 2 önemli değişiklik")


class UiFormatterCopyTests(unittest.TestCase):
    def test_first_seen_copy_not_watchlist(self) -> None:
        rendered = format_priority_reason("Yeni takip edilen şirket")
        self.assertEqual(rendered, "Bu zaman aralığında ilk kez göründü")
        self.assertNotIn("izleme", rendered.lower())

    def test_watchlist_reason_unchanged(self) -> None:
        self.assertEqual(
            format_priority_reason("Kullanıcı izleme listesinde"),
            "Kullanıcı izleme listesinde",
        )

    def test_priority_reasons_batch(self) -> None:
        reasons = format_priority_reasons([
            "Yeni takip edilen şirket",
            "Kullanıcı izleme listesinde",
        ])
        self.assertEqual(reasons[0], "Bu zaman aralığında ilk kez göründü")
        self.assertEqual(reasons[1], "Kullanıcı izleme listesinde")

    def test_legacy_history_note_mapping(self) -> None:
        notes = format_data_quality_notes([
            "Eski taramaların sınırlı snapshot verisi nedeniyle bazı geçmiş "
            "değişimler gösterilemeyebilir."
        ])
        self.assertEqual(notes[0], LEGACY_HISTORY_NOTE)


class UiFormatterPageSmokeTests(unittest.TestCase):
    def test_company_report_compile(self) -> None:
        py_compile.compile("pages/4_Company_Report.py", doraise=True)

    def test_research_monitor_compile(self) -> None:
        py_compile.compile("pages/3_Research_Monitor.py", doraise=True)

    def test_watchlist_page_compile(self) -> None:
        py_compile.compile("pages/6_Izleme_Listesi.py", doraise=True)

    def test_dashboard_compile(self) -> None:
        py_compile.compile("pages/1_Dashboard.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
