from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.sec_contact_config import (
    SECContactConfigError,
    get_sec_contact_email,
    resolve_sec_contact_email,
)


class SECContactConfigTests(unittest.TestCase):
    def test_env_takes_precedence_over_secrets(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets = {"sec": {"contact_email": "secrets@example.com"}}
        with patch("services.sec_contact_config.st", mock_st):
            with patch.dict("os.environ", {"SEC_CONTACT_EMAIL": "env@example.com"}):
                self.assertEqual(get_sec_contact_email(), "env@example.com")

    def test_streamlit_secret_used_when_env_missing(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets = {"sec": {"contact_email": "secrets@example.com"}}
        with patch("services.sec_contact_config.st", mock_st):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(get_sec_contact_email(), "secrets@example.com")

    def test_missing_config_raises(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch("services.sec_contact_config.st", mock_st):
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(SECContactConfigError):
                    get_sec_contact_email()

    def test_allow_empty_returns_blank_when_unconfigured(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch("services.sec_contact_config.st", mock_st):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(resolve_sec_contact_email(allow_empty=True), "")

    def test_no_hardcoded_example_email_in_production_pages(self) -> None:
        page_paths = [
            "pages/1_Dashboard.py",
            "pages/2_Scout_Tarama.py",
            "pages/2_Evren_Motoru.py",
            "pages/4_Company_Report.py",
            "pages/9_Fund_Report.py",
        ]
        for path in page_paths:
            with self.subTest(page=path):
                source = open(path, encoding="utf-8").read()
                self.assertNotIn("nabi-scout@example.com", source)


if __name__ == "__main__":
    unittest.main()
