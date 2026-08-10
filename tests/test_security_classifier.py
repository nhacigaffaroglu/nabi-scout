import unittest

from services.security_classifier import classify_security


class SecurityClassifierTests(unittest.TestCase):
    def test_aapl_common_is_investable(self) -> None:
        result = classify_security(
            symbol="AAPL",
            company_name="Apple Inc.",
        )
        self.assertTrue(result["is_investable_common"])
        self.assertEqual(result["security_type"], "COMMON_STOCK")
        self.assertEqual(result["issuer_category"], "OPERATING_COMPANY")

    def test_sap_foreign_adr_is_investable(self) -> None:
        result = classify_security(
            symbol="SAP",
            company_name="SAP SE",
        )
        self.assertTrue(result["is_investable_common"])
        self.assertEqual(result["security_type"], "COMMON_STOCK")

    def test_tsm_adr_is_investable(self) -> None:
        result = classify_security(
            symbol="TSM",
            company_name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD",
        )
        self.assertTrue(result["is_investable_common"])

    def test_asml_foreign_equity_is_investable(self) -> None:
        result = classify_security(
            symbol="ASML",
            company_name="ASML HOLDING NV",
        )
        self.assertTrue(result["is_investable_common"])

    def test_aciw_common_not_excluded_by_suffix(self) -> None:
        result = classify_security(
            symbol="ACIW",
            company_name="ACI Worldwide, Inc. - Common Stock",
        )
        self.assertTrue(result["is_investable_common"])

    def test_warrant_name_is_excluded(self) -> None:
        result = classify_security(
            symbol="NVDAW",
            company_name="NVIDIA Corporation Warrants",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "EXCLUDED")

    def test_preferred_name_is_excluded(self) -> None:
        result = classify_security(
            symbol="BAC-PL",
            company_name="Bank of America Corporation Preferred Stock",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "EXCLUDED")

    def test_unit_name_is_excluded(self) -> None:
        result = classify_security(
            symbol="SPCEU",
            company_name="Virgin Galactic Holdings Unit",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "EXCLUDED")

    def test_rights_name_is_excluded(self) -> None:
        result = classify_security(
            symbol="XYZR",
            company_name="Example Corp Rights",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "EXCLUDED")

    def test_spac_acquisition_name_is_excluded(self) -> None:
        result = classify_security(
            symbol="AACI",
            company_name="Armada Acquisition Corp II",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "EXCLUDED")

    def test_etf_is_not_common_stock(self) -> None:
        result = classify_security(
            symbol="QQQ",
            company_name="Invesco QQQ Trust",
            is_etf=True,
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "ETF")

    def test_hyphen_warrant_suffix_is_excluded(self) -> None:
        result = classify_security(
            symbol="ABCD-W",
            company_name="Example Corp",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "POSSIBLE_SPECIAL_SECURITY")

    def test_ws_suffix_is_excluded(self) -> None:
        result = classify_security(
            symbol="ABCDEWS",
            company_name="Example Corp",
        )
        self.assertFalse(result["is_investable_common"])
        self.assertEqual(result["security_type"], "POSSIBLE_SPECIAL_SECURITY")


if __name__ == "__main__":
    unittest.main()
