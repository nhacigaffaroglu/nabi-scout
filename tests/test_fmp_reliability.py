import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

import requests

from services.fmp_client import (
    FMPClient,
    FMPError,
    MAX_RATE_LIMIT_BREAKER_SECONDS,
)
from services.scanner_v4_engine import ScannerV4Engine


class FMPClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FMPClient(api_key="test-key", timeout=5)

    def _response(
        self,
        *,
        status_code: int = 200,
        json_data=None,
        headers=None,
    ):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data if json_data is not None else []
        response.headers = headers or {}
        return response

    def test_successful_response(self) -> None:
        payload = [{"symbol": "AAPL", "price": 100}]
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(json_data=payload),
        ):
            data = self.client.quote("AAPL")
        self.assertEqual(data["price"], 100)

    def test_missing_field_returns_empty_dict(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(json_data=[]),
        ):
            data = self.client.ratios_ttm("AAPL")
        self.assertEqual(data, {})

    def test_rate_limit_error_class(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(
                status_code=429,
                headers={"Retry-After": "120"},
            ),
        ):
            with self.assertRaises(FMPError) as ctx:
                self.client.profile("AAPL")
        self.assertEqual(ctx.exception.error_class, "rate_limit")

    def test_rate_limit_short_retry_after_retries_once(self) -> None:
        fail = self._response(
            status_code=429,
            headers={"Retry-After": "1"},
        )
        ok = self._response(json_data=[{"symbol": "AAPL", "price": 10}])
        with patch.object(
            self.client.session,
            "get",
            side_effect=[fail, ok],
        ) as mocked_get:
            with patch("services.fmp_client.time.sleep") as sleep_mock:
                data = self.client.quote("AAPL")
        self.assertEqual(data["price"], 10)
        self.assertEqual(mocked_get.call_count, 2)
        sleep_mock.assert_called_once_with(1.0)
        self.assertEqual(self.client._rate_limited_until, 0.0)

    def test_rate_limit_long_retry_after_opens_breaker_without_sleep(
        self,
    ) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(
                status_code=429,
                headers={"Retry-After": "120"},
            ),
        ):
            with patch("services.fmp_client.time.sleep") as sleep_mock:
                with patch(
                    "services.fmp_client.time.time",
                    return_value=1000.0,
                ):
                    with self.assertRaises(FMPError):
                        self.client.profile("AAPL")
        sleep_mock.assert_not_called()
        self.assertEqual(
            self.client._rate_limited_until,
            1000.0 + MAX_RATE_LIMIT_BREAKER_SECONDS,
        )

    def test_rate_limit_http_date_retry_after(self) -> None:
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=2)
        fail = self._response(
            status_code=429,
            headers={"Retry-After": format_datetime(retry_at, usegmt=True)},
        )
        ok = self._response(json_data=[{"symbol": "AAPL", "price": 10}])
        with patch.object(
            self.client.session,
            "get",
            side_effect=[fail, ok],
        ) as mocked_get:
            with patch("services.fmp_client.time.sleep"):
                data = self.client.quote("AAPL")
        self.assertEqual(data["price"], 10)
        self.assertEqual(mocked_get.call_count, 2)

    def test_plan_restriction_error_class(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(status_code=403),
        ):
            with self.assertRaises(FMPError) as ctx:
                self.client.quote("AAPL")
        self.assertEqual(ctx.exception.error_class, "plan_restricted")

    def test_plan_restriction_does_not_block_other_endpoints(self) -> None:
        forbidden = self._response(status_code=403)
        ok = self._response(
            json_data=[{"symbol": "AAPL", "companyName": "Apple"}],
        )
        with patch.object(
            self.client.session,
            "get",
            side_effect=[forbidden, ok],
        ) as mocked_get:
            with self.assertRaises(FMPError):
                self.client.quote("AAPL")
            profile = self.client.profile("AAPL")
        self.assertEqual(profile["companyName"], "Apple")
        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(self.client._rate_limited_until, 0.0)

    def test_not_found_does_not_block_other_endpoints(self) -> None:
        missing = self._response(status_code=404)
        ok = self._response(json_data=[{"symbol": "AAPL", "price": 10}])
        with patch.object(
            self.client.session,
            "get",
            side_effect=[missing, ok],
        ) as mocked_get:
            with self.assertRaises(FMPError) as ctx:
                self.client.ratios_ttm("AAPL")
            self.assertEqual(ctx.exception.error_class, "not_found")
            quote = self.client.quote("AAPL")
        self.assertEqual(quote["price"], 10)
        self.assertEqual(mocked_get.call_count, 2)

    def test_timeout_error_class(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            side_effect=requests.Timeout("timeout"),
        ):
            with self.assertRaises(FMPError) as ctx:
                self.client.quote("AAPL")
        self.assertEqual(ctx.exception.error_class, "timeout")
        self.assertEqual(self.client._rate_limited_until, 0.0)

    def test_transient_5xx_retries_then_succeeds(self) -> None:
        ok = self._response(json_data=[{"symbol": "AAPL", "price": 10}])
        fail = self._response(status_code=503)
        with patch.object(
            self.client.session,
            "get",
            side_effect=[fail, ok],
        ) as mocked_get:
            data = self.client.quote("AAPL")
        self.assertEqual(data["price"], 10)
        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(self.client._rate_limited_until, 0.0)

    def test_persistent_5xx_does_not_open_rate_limit_breaker(self) -> None:
        fail = self._response(status_code=500)
        with patch.object(
            self.client.session,
            "get",
            return_value=fail,
        ):
            with self.assertRaises(FMPError) as ctx:
                self.client.quote("AAPL")
        self.assertEqual(ctx.exception.error_class, "http_error")
        self.assertEqual(self.client._rate_limited_until, 0.0)

    def test_request_dedup_same_symbol_endpoint(self) -> None:
        payload = [{"symbol": "AAPL", "price": 100}]
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(json_data=payload),
        ) as mocked_get:
            first = self.client.profile("AAPL")
            second = self.client.profile("AAPL")
        self.assertEqual(first, second)
        self.assertEqual(mocked_get.call_count, 1)

    def test_cache_isolation_by_endpoint_and_params(self) -> None:
        profile_payload = [{"symbol": "AAPL", "companyName": "Apple"}]
        quote_payload = [{"symbol": "AAPL", "price": 100}]
        with patch.object(
            self.client.session,
            "get",
            side_effect=[
                self._response(json_data=profile_payload),
                self._response(json_data=quote_payload),
            ],
        ) as mocked_get:
            profile = self.client.profile("AAPL")
            quote = self.client.quote("AAPL")
        self.assertEqual(profile["companyName"], "Apple")
        self.assertEqual(quote["price"], 100)
        self.assertEqual(mocked_get.call_count, 2)

    def test_cache_defensive_copy(self) -> None:
        payload = [{"symbol": "AAPL", "price": 100}]
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(json_data=payload),
        ):
            first = self.client.profile("AAPL")
            first["price"] = 999
            second = self.client.profile("AAPL")
        self.assertEqual(second["price"], 100)

    def test_errors_are_not_cached_as_success(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(status_code=429),
        ):
            with self.assertRaises(FMPError):
                self.client.profile("AAPL")
        with patch.object(self.client.session, "get") as mocked_get:
            with self.assertRaises(FMPError):
                self.client.profile("AAPL")
        mocked_get.assert_not_called()

    def test_rate_limit_short_circuits_second_endpoint(self) -> None:
        with patch.object(
            self.client.session,
            "get",
            return_value=self._response(
                status_code=429,
                headers={"Retry-After": "120"},
            ),
        ) as mocked_get:
            with self.assertRaises(FMPError):
                self.client.profile("AAPL")
            with self.assertRaises(FMPError) as ctx:
                self.client.quote("AAPL")
        self.assertEqual(ctx.exception.error_class, "rate_limit")
        self.assertEqual(mocked_get.call_count, 1)

    def test_reset_scan_state_clears_cache_and_breaker(self) -> None:
        payload = [{"symbol": "AAPL", "price": 100}]
        with patch.object(
            self.client.session,
            "get",
            side_effect=[
                self._response(
                    status_code=429,
                    headers={"Retry-After": "120"},
                ),
                self._response(json_data=payload),
            ],
        ) as mocked_get:
            with self.assertRaises(FMPError):
                self.client.profile("AAPL")
            self.client.reset_scan_state()
            data = self.client.profile("AAPL")
        self.assertEqual(data["price"], 100)
        self.assertEqual(mocked_get.call_count, 2)


class ScannerFMPReliabilityTests(unittest.TestCase):
    def _sec_financials(self):
        return {
            "revenue": 100.0,
            "equity": 50.0,
            "revenue_growth_1y": 10.0,
            "revenue_cagr_3y": 12.0,
            "eps_growth_1y": 8.0,
            "eps_cagr_3y": 10.0,
            "fcf_cagr_3y": 9.0,
            "gross_margin": 40.0,
            "operating_margin": 20.0,
            "net_margin": 15.0,
            "free_cash_flow_margin": 12.0,
            "roic": 18.0,
            "roe": 20.0,
            "roa": 10.0,
            "current_ratio": 1.5,
            "debt_to_equity": 0.8,
            "net_debt_to_fcf": 1.0,
            "interest_coverage": 10.0,
            "share_change_3y": -2.0,
            "payout_ratio": 20.0,
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 5,
            "financial_currency": "USD",
        }

    def _engine(self, *, fmp):
        sec = MagicMock()
        sec.company_facts.return_value = {"facts": {"us-gaap": {}}}
        sec.extract_financials.return_value = self._sec_financials()
        return ScannerV4Engine(fmp, sec)

    def _available_fmp(self):
        fmp = MagicMock()
        fmp.profile.return_value = {
            "companyName": "Test Co",
            "marketCap": 1000,
            "currency": "USD",
        }
        fmp.quote.return_value = {
            "price": 100,
            "marketCap": 1000,
            "pe": 18.0,
            "avgVolume": 500000,
            "currency": "USD",
        }
        return fmp

    def _rate_limited_fmp(self):
        fmp = MagicMock()
        rate_limit = FMPError("rate limit", error_class="rate_limit")
        fmp.profile.side_effect = rate_limit
        fmp.quote.side_effect = rate_limit
        fmp.ratios_ttm.side_effect = rate_limit
        return fmp

    def test_pe_quote_to_ratios_fallback(self) -> None:
        fmp = self._available_fmp()
        fmp.quote.return_value = {"price": 100, "marketCap": 1000}
        fmp.ratios_ttm.return_value = {
            "priceToEarningsRatioTTM": 21.0,
        }
        result = self._engine(fmp=fmp).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertEqual(result["candidate"]["pe_ratio"], 21.0)
        self.assertEqual(result["candidate"]["pe_source"], "ratios_ttm")

    def test_pe_quote_source(self) -> None:
        result = self._engine(fmp=self._available_fmp()).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertEqual(result["candidate"]["pe_ratio"], 18.0)
        self.assertEqual(result["candidate"]["pe_source"], "quote")

    def test_pe_missing_when_no_data_and_endpoints_ok(self) -> None:
        fmp = self._available_fmp()
        fmp.quote.return_value = {"price": 100, "marketCap": 1000}
        fmp.ratios_ttm.return_value = {}
        result = self._engine(fmp=fmp).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertIsNone(result["candidate"]["pe_ratio"])
        self.assertEqual(result["candidate"]["pe_source"], "missing")

    def test_unavailable_endpoint_does_not_become_fake_zero(self) -> None:
        candidate = self._engine(fmp=self._rate_limited_fmp()).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )["candidate"]
        self.assertIsNone(candidate["pe_ratio"])
        self.assertEqual(candidate["pe_source"], "unavailable")
        self.assertNotEqual(candidate["pe_ratio"], 0.0)

    def test_endpoint_status_matrix(self) -> None:
        fmp = MagicMock()
        fmp.profile.side_effect = FMPError(
            "rate limit",
            error_class="rate_limit",
        )
        fmp.quote.side_effect = FMPError(
            "forbidden",
            error_class="plan_restricted",
        )
        fmp.ratios_ttm.side_effect = FMPError(
            "missing",
            error_class="not_found",
        )
        result = self._engine(fmp=fmp).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        status = result["endpoint_status"]
        self.assertEqual(status["fmp_profile"], "RATE_LIMIT")
        self.assertEqual(status["fmp_quote"], "PLAN_RESTRICTED")
        self.assertEqual(status["fmp_ratios_ttm"], "NOT_FOUND")

    def test_available_vs_rate_limited_scoring(self) -> None:
        sec_fields = (
            "revenue_growth",
            "revenue_cagr_3y",
            "eps_growth",
            "eps_cagr_3y",
            "fcf_cagr_3y",
            "gross_margin",
            "operating_margin",
            "net_margin",
            "free_cash_flow_margin",
            "roic",
            "roe",
            "roa",
            "current_ratio",
            "debt_to_equity",
            "net_debt_to_fcf",
            "interest_coverage",
            "share_change_3y",
            "payout_ratio",
        )
        available = self._engine(fmp=self._available_fmp()).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )["candidate"]
        limited = self._engine(fmp=self._rate_limited_fmp()).analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )["candidate"]

        for field in sec_fields:
            self.assertEqual(
                available[field],
                limited[field],
                msg=f"SEC field changed unexpectedly: {field}",
            )

        self.assertEqual(available["quality_score"], limited["quality_score"])
        self.assertEqual(available["growth_score"], limited["growth_score"])
        self.assertIsNotNone(available["pe_ratio"])
        self.assertIsNone(limited["pe_ratio"])
        self.assertGreater(
            available["data_completeness"],
            limited["data_completeness"],
        )

    def test_deterministic_repeated_analysis(self) -> None:
        engine = self._engine(fmp=self._available_fmp())
        first = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )["candidate"]
        second = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )["candidate"]
        self.assertEqual(first["nabi_score"], second["nabi_score"])
        self.assertEqual(
            first["data_completeness"],
            second["data_completeness"],
        )


if __name__ == "__main__":
    unittest.main()
