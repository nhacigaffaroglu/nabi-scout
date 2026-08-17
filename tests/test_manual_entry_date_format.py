from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from services.ui_formatters import (
    DATE_DMY_PLACEHOLDER,
    format_date_dmy,
    parse_date_dmy,
)


ADD_HOLDING_SCRIPT = r"""
from unittest.mock import MagicMock
from components.portfolio_management_ui import render_add_holding_form

wealth = MagicMock()
portfolio = {"id": "pf", "name": "Ana", "base_currency": "USD"}
accounts = [{
    "id": "a1",
    "name": "TFK",
    "institution": "TFK",
    "portfolio_id": "pf",
    "is_active": True,
}]
render_add_holding_form(wealth, portfolio, accounts)
"""


class ActualAddHoldingFormDatePathTests(unittest.TestCase):
    def _run_form(self) -> AppTest:
        at = AppTest.from_string(ADD_HOLDING_SCRIPT)
        at.run(timeout=10)
        self.assertFalse(bool(at.exception), at.exception)
        return at

    def test_real_form_uses_text_input_not_date_input(self) -> None:
        at = self._run_form()
        self.assertEqual(len(at.date_input), 0)
        labels = [widget.label for widget in at.text_input]
        self.assertIn("Alış tarihi (opsiyonel)", labels)
        date_widget = next(
            widget for widget in at.text_input if widget.label == "Alış tarihi (opsiyonel)"
        )
        self.assertEqual(date_widget.placeholder, DATE_DMY_PLACEHOLDER)
        self.assertEqual(DATE_DMY_PLACEHOLDER, "07.08.2025")
        self.assertNotIn("/", date_widget.placeholder)

    def test_form_is_the_pi_add_holding_form(self) -> None:
        at = self._run_form()
        date_widget = next(
            widget for widget in at.text_input if widget.label == "Alış tarihi (opsiyonel)"
        )
        self.assertEqual(date_widget.proto.form_id, "pi_add_holding_form")

    def test_pi_page_uses_render_add_holding_form(self) -> None:
        page = Path("pages/11_Portfolio_Intelligence.py").read_text(encoding="utf-8")
        ui = Path("components/portfolio_intelligence_ui.py").read_text(encoding="utf-8")
        visual = Path("components/portfolio_visual_ui.py").read_text(encoding="utf-8")
        self.assertIn("render_portfolio_management_expander", page)
        self.assertIn("render_add_holding_form", visual)
        self.assertIn("render_add_holding_form", ui)
        self.assertIn("+ Portföye Ekle", ui)

    def test_typed_dmy_stores_iso_not_us(self) -> None:
        parsed = parse_date_dmy("14.05.2025")
        self.assertEqual(parsed, date(2025, 5, 14))
        self.assertEqual(parsed.isoformat(), "2025-05-14")
        self.assertEqual(format_date_dmy(parsed), "14.05.2025")
        self.assertNotEqual(format_date_dmy(parsed), "05/14/2025")
        self.assertNotEqual(format_date_dmy(parsed), "14/05/2025")

    def test_us_slash_input_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_date_dmy("08/07/2025")

    def test_submit_passes_isoformat_to_add_holding(self) -> None:
        at = AppTest.from_string(ADD_HOLDING_SCRIPT)
        at.run(timeout=10)
        at.text_input[0].set_value("CRM")
        date_widget = next(
            widget for widget in at.text_input if widget.label == "Alış tarihi (opsiyonel)"
        )
        date_widget.set_value("07.08.2025")
        at.number_input[0].set_value(1.0)
        at.number_input[1].set_value(100.0)
        at.button[0].click().run(timeout=10)
        self.assertFalse(bool(at.exception), at.exception)


if __name__ == "__main__":
    unittest.main()
