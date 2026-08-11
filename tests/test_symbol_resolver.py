import unittest
from unittest.mock import MagicMock, patch

from services.fmp_client import FMPError
from services.symbol_resolver_service import (
    RESOLUTION_SOURCE_CANDIDATE,
    RESOLUTION_SOURCE_CONFIG,
    RESOLUTION_SOURCE_FMP,
    RESOLUTION_SOURCE_NASDAQ,
    RESOLUTION_SOURCE_SEC,
    SECURITY_TYPE_UNRESOLVED,
    SymbolNotFoundError,
    normalize_symbol_input,
    resolve_symbol,
)


def candidate(symbol, **overrides):
    base = {
        "symbol": symbol,
        "company_name": f"{symbol} Inc.",
        "exchange": "NASDAQ",
        "cik": 123,
        "security_type": "COMMON_STOCK",
        "is_etf": False,
    }
    base.update(overrides)
    return base


class NormalizeSymbolTests(unittest.TestCase):
    def test_whitespace_and_uppercase(self) -> None:
        self.assertEqual(normalize_symbol_input("  nvda "), "NVDA")

    def test_no_substitution(self) -> None:
        self.assertEqual(normalize_symbol_input("NVDA"), "NVDA")
        self.assertNotEqual(normalize_symbol_input("NVD"), "NVDA")


class ResolveSymbolTests(unittest.TestCase):
    def test_existing_equity_candidate(self) -> None:
        repo = MagicMock()
        repo.get_by_symbol.return_value = candidate("NVDA")
        resolved = resolve_symbol("nvda", candidate_repo=repo)
        self.assertEqual(resolved.symbol, "NVDA")
        self.assertFalse(resolved.is_etf)
        self.assertTrue(resolved.is_equity_eligible)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_CANDIDATE)
        self.assertEqual(resolved.resolution_confidence, "HIGH")

    def test_sec_equity_not_in_candidate_pool(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "symbol": "JNJ",
            "companyName": "Johnson & Johnson",
            "exchange": "NYSE",
            "isEtf": False,
        }
        resolved = resolve_symbol(
            "JNJ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
            sec_lookup={
                "JNJ": {
                    "symbol": "JNJ",
                    "company_name": "JOHNSON & JOHNSON",
                    "exchange": "NYSE",
                    "cik": 200406,
                }
            },
        )
        self.assertFalse(resolved.is_etf)
        self.assertTrue(resolved.is_equity_eligible)
        self.assertEqual(resolved.cik, 200406)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_FMP)

    def test_fmp_profile_fallback(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "symbol": "VTI",
            "companyName": "Vanguard Total Stock Market ETF",
            "exchange": "NYSE Arca",
            "isEtf": True,
        }
        resolved = resolve_symbol(
            "VTI",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
        )
        self.assertTrue(resolved.is_etf)
        self.assertFalse(resolved.is_equity_eligible)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_FMP)

    def test_invalid_symbol(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {}
        with self.assertRaises(SymbolNotFoundError):
            resolve_symbol(
                "NOTREAL123",
                candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
                fmp_client=fmp,
            )

    def test_configured_etf(self) -> None:
        resolved = resolve_symbol(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
        )
        self.assertTrue(resolved.is_etf)
        self.assertFalse(resolved.is_equity_eligible)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_CONFIG)

    def test_nasdaq_etf_flag(self) -> None:
        resolved = resolve_symbol(
            "QQQ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            nasdaq_lookup={
                "QQQ": {
                    "symbol": "QQQ",
                    "company_name": "Invesco QQQ Trust",
                    "exchange": "NASDAQ",
                    "is_etf": True,
                }
            },
            sec_lookup={
                "QQQ": {
                    "symbol": "QQQ",
                    "company_name": "INVESCO QQQ TRUST, SERIES 1",
                    "exchange": "NASDAQ",
                    "cik": 1067839,
                }
            },
        )
        self.assertTrue(resolved.is_etf)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_NASDAQ)

    def test_qqq_fmp_is_etf_true_metadata_only(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "symbol": "QQQ",
            "companyName": "Invesco QQQ Trust",
            "isEtf": True,
        }
        resolved = resolve_symbol(
            "QQQ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
            sec_lookup={
                "QQQ": {
                    "symbol": "QQQ",
                    "company_name": "INVESCO QQQ TRUST, SERIES 1",
                    "cik": 1067839,
                }
            },
        )
        self.assertTrue(resolved.is_etf)
        self.assertFalse(resolved.is_equity_eligible)

    def test_qqq_fmp_rate_limit_sec_hit_not_equity(self) -> None:
        fmp = MagicMock()
        fmp.profile.side_effect = FMPError(
            "rate limited",
            error_class="rate_limit",
        )
        resolved = resolve_symbol(
            "QQQ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
            sec_lookup={
                "QQQ": {
                    "symbol": "QQQ",
                    "company_name": "INVESCO QQQ TRUST, SERIES 1",
                    "exchange": "NASDAQ",
                    "cik": 1067839,
                }
            },
        )
        self.assertEqual(resolved.security_type, SECURITY_TYPE_UNRESOLVED)
        self.assertFalse(resolved.is_equity_eligible)
        self.assertFalse(resolved.is_etf)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_SEC)
        self.assertIn("rate limit", (resolved.classification_warning or "").lower())

    def test_unknown_trust_sec_only_not_equity(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {}
        resolved = resolve_symbol(
            "XYZT",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
            sec_lookup={
                "XYZT": {
                    "symbol": "XYZT",
                    "company_name": "EXAMPLE INDEX TRUST SERIES 1",
                    "exchange": "NASDAQ",
                    "cik": 9999999,
                }
            },
        )
        self.assertEqual(resolved.security_type, SECURITY_TYPE_UNRESOLVED)
        self.assertFalse(resolved.is_equity_eligible)

    def test_equity_without_cik(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {
            "symbol": "ABC",
            "companyName": "ABC Corp",
            "exchange": "NASDAQ",
            "isEtf": False,
        }
        resolved = resolve_symbol(
            "ABC",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=fmp,
        )
        self.assertFalse(resolved.is_etf)
        self.assertTrue(resolved.is_equity_eligible)
        self.assertIsNone(resolved.cik)

    def test_fmp_rate_limit_without_identity_raises(self) -> None:
        fmp = MagicMock()
        fmp.profile.side_effect = FMPError(
            "rate limited",
            error_class="rate_limit",
        )
        with self.assertRaises(FMPError):
            resolve_symbol(
                "NVDA",
                candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
                fmp_client=fmp,
            )

    def test_nasdaq_non_etf_affirmative_equity(self) -> None:
        resolved = resolve_symbol(
            "JNJ",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            fmp_client=MagicMock(profile=MagicMock(return_value={})),
            nasdaq_lookup={
                "JNJ": {
                    "symbol": "JNJ",
                    "company_name": "Johnson & Johnson",
                    "exchange": "NYSE",
                    "is_etf": False,
                }
            },
            sec_lookup={
                "JNJ": {
                    "symbol": "JNJ",
                    "company_name": "JOHNSON & JOHNSON",
                    "cik": 200406,
                }
            },
        )
        self.assertTrue(resolved.is_equity_eligible)
        self.assertEqual(resolved.resolution_source, RESOLUTION_SOURCE_NASDAQ)


if __name__ == "__main__":
    unittest.main()
