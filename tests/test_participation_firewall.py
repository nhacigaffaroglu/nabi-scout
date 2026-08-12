import unittest
from typing import Any, Dict

from services.candidate_persistence import prepare_candidate_payload
from services.candidate_surface_service import filter_equity_candidate_surface
from services.decision_engine import build_decision
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.research_intelligence_engine import enrich_research
from services.scanner_v4_engine import ScannerV4Engine
from services.scanner_v8_engine import ScannerV8Engine


def _strong_score_kwargs(**overrides: Any) -> Dict[str, Any]:
    kwargs = {
        "revenue_growth_1y": 18.0,
        "revenue_cagr_3y": 16.0,
        "eps_growth_1y": 20.0,
        "eps_cagr_3y": 18.0,
        "fcf_cagr_3y": 15.0,
        "gross_margin": 55.0,
        "operating_margin": 28.0,
        "net_margin": 22.0,
        "fcf_margin": 20.0,
        "roic": 22.0,
        "roe": 24.0,
        "roa": 12.0,
        "current_ratio": 1.8,
        "debt_to_equity": 0.4,
        "net_debt_to_fcf": 1.5,
        "interest_coverage": 12.0,
        "pe_ratio": 18.0,
        "price_to_sales": 4.0,
        "price_to_book": 3.0,
        "share_change_3y": -2.0,
        "payout_ratio": 25.0,
        "market_cap": 50_000_000_000,
        "average_volume": 5_000_000,
        "portfolio_fit": 70.0,
        "participation_score": 60.0,
        "participation_status": "Kontrol Et",
        "completeness": 90.0,
    }
    kwargs.update(overrides)
    return kwargs


class FakeFMP:
    def __init__(self, *, market_cap: float, currency: str = "USD") -> None:
        self.market_cap = market_cap
        self.currency = currency

    def profile(self, symbol: str) -> Dict[str, Any]:
        return {
            "companyName": symbol,
            "currency": self.currency,
            "marketCap": self.market_cap,
            "sector": "Technology",
        }

    def quote(self, symbol: str) -> Dict[str, Any]:
        return {
            "price": 100,
            "marketCap": self.market_cap,
            "currency": self.currency,
            "pe": 18,
        }

    def ratios_ttm(self, symbol: str) -> Dict[str, Any]:
        return {}


class FakeSEC:
    def __init__(self, financials: Dict[str, Any]) -> None:
        self.financials = financials

    def company_facts(self, cik: int | str) -> Dict[str, Any]:
        return {"facts": {"us-gaap": {}}}

    def extract_financials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.financials


def _scanner_financials() -> Dict[str, Any]:
    return {
        "revenue": 100_000_000,
        "equity": 50_000_000,
        "financial_currency": "USD",
        "financial_taxonomy": "us-gaap",
        "financial_period_end": "2025-12-31",
        "annual_periods_found": 5,
        "revenue_growth_1y": 18.0,
        "revenue_cagr_3y": 16.0,
        "eps_growth_1y": 20.0,
        "eps_cagr_3y": 18.0,
        "fcf_cagr_3y": 15.0,
        "gross_margin": 55.0,
        "operating_margin": 28.0,
        "net_margin": 22.0,
        "free_cash_flow_margin": 20.0,
        "roic": 22.0,
        "roe": 24.0,
        "roa": 12.0,
        "current_ratio": 1.8,
        "debt_to_equity": 0.4,
        "net_debt_to_fcf": 1.5,
        "interest_coverage": 12.0,
        "share_change_3y": -2.0,
        "payout_ratio": 25.0,
    }


class NabiScoreParticipationFirewallTests(unittest.TestCase):
    def test_participation_score_does_not_change_nabi_score(self) -> None:
        base = _strong_score_kwargs()
        scores = [
            calculate_nabi_score_v4(**{**base, "participation_score": value})[
                "nabi_score"
            ]
            for value in (100, 60, 0)
        ]
        self.assertEqual(len(set(scores)), 1)

    def test_participation_status_does_not_change_nabi_score(self) -> None:
        base = _strong_score_kwargs()
        scores = [
            calculate_nabi_score_v4(
                **{
                    **base,
                    "participation_status": status,
                    "participation_score": score,
                }
            )["nabi_score"]
            for status, score in (
                ("Uygun", 100),
                ("Kontrol Et", 60),
                ("Uygun Değil", 0),
            )
        ]
        self.assertEqual(len(set(scores)), 1)

    def test_uygun_degil_does_not_force_zero_score(self) -> None:
        result = calculate_nabi_score_v4(
            **_strong_score_kwargs(
                participation_status="Uygun Değil",
                participation_score=0,
            )
        )
        self.assertGreater(result["nabi_score"], 0)
        self.assertNotEqual(result["decision"], "ELE")

    def test_uygun_degil_does_not_force_ele_decision(self) -> None:
        result = calculate_nabi_score_v4(
            **_strong_score_kwargs(
                participation_status="Uygun Değil",
                participation_score=0,
            )
        )
        self.assertNotEqual(result["decision"], "ELE")

    def test_score_remains_on_zero_to_hundred_scale(self) -> None:
        result = calculate_nabi_score_v4(**_strong_score_kwargs())
        self.assertGreaterEqual(result["nabi_score"], 0)
        self.assertLessEqual(result["nabi_score"], 100)

    def test_decision_output_invariant_under_participation_only_changes(self) -> None:
        base = _strong_score_kwargs()
        decisions = [
            calculate_nabi_score_v4(
                **{
                    **base,
                    "participation_status": status,
                    "participation_score": score,
                }
            )["decision"]
            for status, score in (
                ("Uygun", 100),
                ("Kontrol Et", 60),
                ("Uygun Değil", 0),
            )
        ]
        self.assertEqual(len(set(decisions)), 1)


class DecisionEngineParticipationFirewallTests(unittest.TestCase):
    def _candidate_from_score(self, score_payload: Dict[str, Any]) -> Dict[str, Any]:
        candidate = {
            "symbol": "NVDA",
            "data_completeness": 90.0,
            "annual_periods_found": 10,
            "research_confidence": 85.0,
            "score_positive_factors": score_payload.get("positive_reasons") or [],
            "score_negative_factors": score_payload.get("negative_reasons") or [],
            "hard_flags": score_payload.get("hard_flags") or [],
        }
        candidate.update(score_payload)
        enrich_research(candidate, errors=[])
        return candidate

    def test_decision_label_invariant_when_participation_metadata_differs(self) -> None:
        score_payload = calculate_nabi_score_v4(**_strong_score_kwargs())
        labels = []
        for status in ("Uygun", "Kontrol Et", "Uygun Değil"):
            candidate = self._candidate_from_score(score_payload)
            candidate["participation_status"] = status
            candidate["participation_score"] = (
                100 if status == "Uygun" else 0 if status == "Uygun Değil" else 60
            )
            labels.append(candidate["decision_label"])
        self.assertEqual(len(set(labels)), 1)

    def test_build_decision_does_not_read_participation_fields(self) -> None:
        candidate = {
            "nabi_score": 78.0,
            "research_confidence": 80.0,
            "risk_score": 70.0,
            "valuation_score": 65.0,
            "quality_score": 75.0,
            "growth_score": 72.0,
            "data_completeness": 88.0,
            "score_positive_factors": [],
            "score_negative_factors": [],
            "hard_flags": [],
            "participation_status": "Uygun Değil",
            "participation_score": 0,
        }
        first = build_decision(candidate)
        candidate["participation_status"] = "Uygun"
        candidate["participation_score"] = 100
        second = build_decision(candidate)
        self.assertEqual(first["decision_label"], second["decision_label"])


class ScannerParticipationFirewallTests(unittest.TestCase):
    def _analyze_with_participation(
        self,
        *,
        participation_status: str,
        participation_score: int,
    ) -> Dict[str, Any]:
        engine = ScannerV4Engine(
            FakeFMP(market_cap=50_000_000_000),
            FakeSEC(_scanner_financials()),
        )
        return engine.analyze(
            symbol="NVDA",
            cik=123,
            company_name="NVIDIA",
            exchange="NASDAQ",
            participation_status=participation_status,
            participation_score=participation_score,
        )["candidate"]

    def test_scanner_v4_participation_only_changes_do_not_affect_score(self) -> None:
        variants = [
            self._analyze_with_participation(
                participation_status=status,
                participation_score=score,
            )
            for status, score in (
                ("Uygun", 100),
                ("Kontrol Et", 60),
                ("Uygun Değil", 0),
            )
        ]
        scores = [item["nabi_score"] for item in variants]
        decisions = [item["decision"] for item in variants]
        self.assertEqual(len(set(scores)), 1)
        self.assertEqual(len(set(decisions)), 1)

    def test_scanner_v4_still_persists_participation_metadata(self) -> None:
        candidate = self._analyze_with_participation(
            participation_status="Uygun",
            participation_score=100,
        )
        self.assertEqual(candidate["participation_status"], "Uygun")
        self.assertEqual(candidate["participation_score"], 100)

    def test_scanner_v8_path_participation_invariant(self) -> None:
        engine = ScannerV8Engine(
            FakeFMP(market_cap=50_000_000_000),
            FakeSEC(_scanner_financials()),
        )
        results = []
        for status, score in (
            ("Uygun", 100),
            ("Kontrol Et", 60),
            ("Uygun Değil", 0),
        ):
            candidate = engine.analyze(
                symbol="NVDA",
                cik=123,
                company_name="NVIDIA",
                exchange="NASDAQ",
                participation_status=status,
                participation_score=score,
            )["candidate"]
            results.append(candidate)

        scores = [item["nabi_score"] for item in results]
        decision_labels = [item.get("decision_label") for item in results]
        self.assertEqual(len(set(scores)), 1)
        self.assertEqual(len(set(decision_labels)), 1)
        self.assertEqual(results[0]["participation_status"], "Uygun")
        self.assertEqual(results[2]["participation_status"], "Uygun Değil")


class ParticipationPersistenceCompatibilityTests(unittest.TestCase):
    def test_candidate_payload_retains_participation_fields(self) -> None:
        payload = prepare_candidate_payload(
            {
                "symbol": "NVDA",
                "market": "ABD",
                "asset_type": "Hisse",
                "participation_status": "Kontrol Et",
                "participation_score": 60,
                "nabi_score": 75.0,
            }
        )
        self.assertEqual(payload["participation_status"], "Kontrol Et")
        self.assertEqual(payload["participation_score"], 60)


class EquitySurfaceFirewallRegressionTests(unittest.TestCase):
    def test_legacy_etf_rows_remain_filtered(self) -> None:
        rows = [
            {"symbol": "NVDA", "asset_type": "Hisse"},
            {"symbol": "SPUS", "asset_type": "ETF"},
            {"symbol": "HLAL", "issuer_category": "FUND"},
            {"symbol": "SPSK", "security_type": "ETF"},
        ]
        filtered = filter_equity_candidate_surface(rows)
        self.assertEqual([row["symbol"] for row in filtered], ["NVDA"])


if __name__ == "__main__":
    unittest.main()
