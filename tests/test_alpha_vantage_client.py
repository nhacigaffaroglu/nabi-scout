import json
import unittest
from unittest.mock import MagicMock, patch

from services.alpha_vantage_adapter import (
    alpha_daily_rows,
    normalize_alpha_expense_ratio,
    normalize_alpha_weight_pct,
    parse_alpha_holdings,
)
from services.alpha_vantage_client import (
    STATUS_AUTH,
    STATUS_MALFORMED,
    STATUS_OK,
    STATUS_PREMIUM_REQUIRED,
    STATUS_RATE_LIMIT,
    AlphaVantageClient,
    AlphaVantageError,
    classify_alpha_payload,
)


class AlphaVantageClientTests(unittest.TestCase):
    def test_from_env(self) -> None:
        with patch.dict("os.environ", {"ALPHA_VANTAGE_API_KEY": "test-key"}):
            client = AlphaVantageClient.from_env()
            self.assertEqual(client.api_key, "test-key")

    def test_from_streamlit_secrets(self) -> None:
        secrets = {"alpha_vantage": {"api_key": "secret-key"}}
        with patch("services.alpha_vantage_client.st.secrets", secrets):
            client = AlphaVantageClient.from_streamlit_secrets()
            self.assertEqual(client.api_key, "secret-key")

    def test_missing_key_raises_auth(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            AlphaVantageClient("")
        self.assertEqual(ctx.exception.status, STATUS_AUTH)

    def test_key_not_exposed_in_exception(self) -> None:
        client = AlphaVantageClient("super-secret-key")
        with patch.object(client, "_request", return_value={"Error Message": "Invalid API key"}):
            with self.assertRaises(AlphaVantageError) as ctx:
                client.etf_profile("SPUS")
        self.assertNotIn("super-secret-key", str(ctx.exception))

    def test_etf_profile_success(self) -> None:
        payload = {
            "net_assets": "100",
            "net_expense_ratio": "0.0045",
            "holdings": [{"symbol": "AAPL", "description": "Apple", "weight": "0.1"}],
        }
        client = AlphaVantageClient("key")
        with patch.object(client, "_request", return_value=payload):
            result = client.etf_profile("SPUS")
        self.assertEqual(result["net_assets"], "100")

    def test_rate_limit_note(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            classify_alpha_payload({"Note": "Thank you for using Alpha Vantage"}, expect="etf_profile")
        self.assertEqual(ctx.exception.status, STATUS_RATE_LIMIT)

    def test_premium_information(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            classify_alpha_payload(
                {"Information": "The premium endpoint selected is not within your current plan."},
                expect="etf_profile",
            )
        self.assertEqual(ctx.exception.status, STATUS_PREMIUM_REQUIRED)

    def test_auth_error_message(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            classify_alpha_payload({"Error Message": "Invalid API call. Check apikey."}, expect="etf_profile")
        self.assertEqual(ctx.exception.status, STATUS_AUTH)

    def test_malformed_payload(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            classify_alpha_payload({}, expect="etf_profile")
        self.assertEqual(ctx.exception.status, STATUS_MALFORMED)

    def test_network_error(self) -> None:
        client = AlphaVantageClient("key")
        with patch.object(client, "_request", side_effect=AlphaVantageError("network", status=STATUS_MALFORMED)):
            with self.assertRaises(AlphaVantageError):
                client.etf_profile("SPUS")

    def test_time_series_daily_parse(self) -> None:
        payload = {
            "Meta Data": {"2. Symbol": "SPUS"},
            "Time Series (Daily)": {
                "2024-01-02": {"4. close": "100.0", "5. volume": "1000"},
                "2024-01-03": {"4. close": "101.0", "5. volume": "1100"},
            },
        }
        rows = alpha_daily_rows(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2024-01-02")
        self.assertEqual(rows[0]["close"], "100.0")

    def test_time_series_premium(self) -> None:
        client = AlphaVantageClient("key")
        with patch.object(
            client,
            "_request",
            return_value={"Information": "premium endpoint not in plan"},
        ):
            with self.assertRaises(AlphaVantageError) as ctx:
                client.time_series_daily("SPUS")
            self.assertEqual(ctx.exception.status, STATUS_PREMIUM_REQUIRED)

    def test_global_quote_parse(self) -> None:
        payload = {
            "Global Quote": {
                "01. symbol": "TUPRS.IS",
                "05. price": "180.5000",
                "07. latest trading day": "2026-08-19",
            }
        }
        client = AlphaVantageClient("key")
        with patch.object(client, "_request", return_value=payload):
            quote = client.global_quote("TUPRS.IS")
        self.assertEqual(quote["05. price"], "180.5000")
        self.assertEqual(classify_alpha_payload(payload, expect="global_quote"), STATUS_OK)

    def test_global_quote_empty_is_not_found(self) -> None:
        with self.assertRaises(AlphaVantageError) as ctx:
            classify_alpha_payload({"Global Quote": {}}, expect="global_quote")
        self.assertEqual(ctx.exception.status, "NOT_FOUND")

    def test_currency_exchange_rate_parse(self) -> None:
        payload = {
            "Realtime Currency Exchange Rate": {
                "1. From_Currency Code": "USD",
                "3. To_Currency Code": "TRY",
                "5. Exchange Rate": "41.25000000",
                "6. Last Refreshed": "2026-08-19 12:00:00",
            }
        }
        client = AlphaVantageClient("key")
        with patch.object(client, "_request", return_value=payload):
            block = client.currency_exchange_rate("USD", "TRY")
        self.assertEqual(block["5. Exchange Rate"], "41.25000000")
        self.assertEqual(
            classify_alpha_payload(payload, expect="currency_exchange_rate"),
            STATUS_OK,
        )


class AlphaNormalizationTests(unittest.TestCase):
    def test_expense_decimal_ratio(self) -> None:
        self.assertEqual(normalize_alpha_expense_ratio("0.0045"), 0.45)

    def test_expense_float_ratio(self) -> None:
        self.assertEqual(normalize_alpha_expense_ratio(0.0045), 0.45)

    def test_expense_percent_string(self) -> None:
        self.assertEqual(normalize_alpha_expense_ratio("0.45%"), 0.45)

    def test_expense_invalid(self) -> None:
        self.assertIsNone(normalize_alpha_expense_ratio("n/a"))
        self.assertIsNone(normalize_alpha_expense_ratio(-1))
        self.assertIsNone(normalize_alpha_expense_ratio(99))

    def test_holdings_weight_fraction(self) -> None:
        self.assertEqual(normalize_alpha_weight_pct("0.1332"), 13.32)

    def test_holdings_weight_percent_string(self) -> None:
        self.assertEqual(normalize_alpha_weight_pct("13.32%"), 13.32)

    def test_holdings_invalid_skipped(self) -> None:
        holdings = parse_alpha_holdings([
            {"symbol": "AAPL", "description": "Apple", "weight": "bad"},
            {"symbol": "MSFT", "description": "Microsoft", "weight": "0.05"},
        ])
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].symbol, "MSFT")

    def test_top10_concentration_no_double_multiply(self) -> None:
        holdings = parse_alpha_holdings([
            {"symbol": "A", "weight": "0.30"},
            {"symbol": "B", "weight": "0.25"},
        ])
        weights = [holding.weight_pct for holding in holdings]
        self.assertEqual(sum(weights), 55.0)


if __name__ == "__main__":
    unittest.main()
