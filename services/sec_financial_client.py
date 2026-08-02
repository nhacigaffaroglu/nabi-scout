from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

import requests


class SECFinancialError(RuntimeError):
    pass


class SECFinancialClient:
    BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"

    def __init__(
        self,
        *,
        contact_email: str,
        timeout: int = 30,
    ) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                f"NABI Scout investment research app "
                f"contact={contact_email}"
            ),
            "Accept-Encoding": "gzip, deflate",
        })

    def company_facts(self, cik: int | str) -> Dict[str, Any]:
        cik_text = str(cik).strip().zfill(10)
        url = f"{self.BASE_URL}/CIK{cik_text}.json"

        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SECFinancialError(
                "SEC Company Facts bağlantı hatası."
            ) from exc

        if response.status_code == 404:
            raise SECFinancialError(
                f"SEC Company Facts bulunamadı: CIK {cik_text}"
            )
        if response.status_code != 200:
            raise SECFinancialError(
                f"SEC Company Facts HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise SECFinancialError(
                "SEC Company Facts geçerli JSON döndürmedi."
            ) from exc

    def extract_financials(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:
        facts = (
            payload.get("facts", {})
            .get("us-gaap", {})
        )

        revenue_series = self._series(
            facts,
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ],
            ["USD"],
        )
        net_income_series = self._series(
            facts,
            ["NetIncomeLoss", "ProfitLoss"],
            ["USD"],
        )
        operating_income_series = self._series(
            facts,
            ["OperatingIncomeLoss"],
            ["USD"],
        )
        gross_profit_series = self._series(
            facts,
            ["GrossProfit"],
            ["USD"],
        )
        operating_cash_series = self._series(
            facts,
            [
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ],
            ["USD"],
        )
        capex_series = self._series(
            facts,
            [
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsForAdditionsToPropertyPlantAndEquipment",
            ],
            ["USD"],
        )
        pretax_series = self._series(
            facts,
            [
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ],
            ["USD"],
        )
        tax_series = self._series(
            facts,
            ["IncomeTaxExpenseBenefit"],
            ["USD"],
        )
        equity_series = self._series(
            facts,
            [
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ],
            ["USD"],
            instant=True,
        )
        cash_series = self._series(
            facts,
            [
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ],
            ["USD"],
            instant=True,
        )
        current_assets_series = self._series(
            facts,
            ["AssetsCurrent"],
            ["USD"],
            instant=True,
        )
        current_liabilities_series = self._series(
            facts,
            ["LiabilitiesCurrent"],
            ["USD"],
            instant=True,
        )
        debt_series = self._series(
            facts,
            [
                "LongTermDebtAndFinanceLeaseObligationsCurrent",
                "LongTermDebtCurrent",
                "LongTermDebtNoncurrent",
                "LongTermDebt",
            ],
            ["USD"],
            instant=True,
            combine_same_end=True,
        )
        eps_series = self._series(
            facts,
            [
                "EarningsPerShareDiluted",
                "EarningsPerShareBasicAndDiluted",
            ],
            ["USD/shares", "USD / shares"],
        )

        revenue_latest, revenue_previous = self._latest_two(
            revenue_series
        )
        net_income_latest, _ = self._latest_two(
            net_income_series
        )
        operating_income_latest, _ = self._latest_two(
            operating_income_series
        )
        gross_profit_latest, _ = self._latest_two(
            gross_profit_series
        )
        operating_cash_latest, _ = self._latest_two(
            operating_cash_series
        )
        capex_latest, _ = self._latest_two(capex_series)
        pretax_latest, _ = self._latest_two(pretax_series)
        tax_latest, _ = self._latest_two(tax_series)
        eps_latest, eps_previous = self._latest_two(eps_series)

        equity_latest, _ = self._latest_two(equity_series)
        cash_latest, _ = self._latest_two(cash_series)
        current_assets_latest, _ = self._latest_two(
            current_assets_series
        )
        current_liabilities_latest, _ = self._latest_two(
            current_liabilities_series
        )
        debt_latest, _ = self._latest_two(debt_series)

        free_cash_flow = None
        if operating_cash_latest is not None:
            free_cash_flow = (
                operating_cash_latest
                - abs(capex_latest or 0)
            )

        revenue_growth = self._growth(
            revenue_latest,
            revenue_previous,
        )
        eps_growth = self._growth(
            eps_latest,
            eps_previous,
        )

        gross_margin = self._margin(
            gross_profit_latest,
            revenue_latest,
        )
        operating_margin = self._margin(
            operating_income_latest,
            revenue_latest,
        )
        net_margin = self._margin(
            net_income_latest,
            revenue_latest,
        )
        fcf_margin = self._margin(
            free_cash_flow,
            revenue_latest,
        )

        current_ratio = None
        if (
            current_assets_latest is not None
            and current_liabilities_latest
        ):
            current_ratio = (
                current_assets_latest
                / current_liabilities_latest
            )

        tax_rate = 0.21
        if pretax_latest and tax_latest is not None:
            calculated = tax_latest / pretax_latest
            if 0 <= calculated <= 0.5:
                tax_rate = calculated

        nopat = None
        if operating_income_latest is not None:
            nopat = operating_income_latest * (1 - tax_rate)

        invested_capital = None
        if equity_latest is not None:
            invested_capital = (
                equity_latest
                + (debt_latest or 0)
                - (cash_latest or 0)
            )

        roic = None
        if nopat is not None and invested_capital:
            roic = (nopat / invested_capital) * 100

        debt_to_equity = None
        if debt_latest is not None and equity_latest:
            debt_to_equity = debt_latest / equity_latest

        net_debt = None
        if debt_latest is not None:
            net_debt = debt_latest - (cash_latest or 0)

        return {
            "revenue": revenue_latest,
            "revenue_growth": revenue_growth,
            "eps": eps_latest,
            "eps_growth": eps_growth,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "operating_cash_flow": operating_cash_latest,
            "capital_expenditure": capex_latest,
            "free_cash_flow": free_cash_flow,
            "free_cash_flow_margin": fcf_margin,
            "equity": equity_latest,
            "cash": cash_latest,
            "total_debt": debt_latest,
            "net_debt": net_debt,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "roic": roic,
            "financial_period_end": self._latest_end(
                revenue_series
            ),
        }

    def _series(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
        *,
        instant: bool = False,
        combine_same_end: bool = False,
    ) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []

        for tag in tags:
            fact = facts.get(tag, {})
            unit_map = fact.get("units", {})

            entries = []
            for unit in units:
                if unit in unit_map:
                    entries = unit_map[unit]
                    break

            for item in entries:
                form = str(item.get("form") or "")
                fp = str(item.get("fp") or "")
                if form not in {"10-K", "10-K/A", "20-F", "40-F"}:
                    continue
                if not instant and fp not in {"FY", ""}:
                    continue

                value = self._number(item.get("val"))
                end = item.get("end")
                if value is None or not end:
                    continue

                if not instant:
                    start = item.get("start")
                    if start:
                        try:
                            days = (
                                date.fromisoformat(end)
                                - date.fromisoformat(start)
                            ).days
                        except ValueError:
                            days = 365
                        if days < 300 or days > 430:
                            continue

                collected.append({
                    "value": value,
                    "end": end,
                    "filed": item.get("filed") or "",
                    "tag": tag,
                })

            if collected and not combine_same_end:
                break

        if combine_same_end:
            totals: Dict[str, Dict[str, Any]] = {}
            for item in collected:
                end = item["end"]
                if end not in totals:
                    totals[end] = {
                        "value": 0.0,
                        "end": end,
                        "filed": item["filed"],
                    }
                totals[end]["value"] += item["value"]
                totals[end]["filed"] = max(
                    totals[end]["filed"],
                    item["filed"],
                )
            collected = list(totals.values())

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in collected:
            end = item["end"]
            current = deduped.get(end)
            if (
                current is None
                or item["filed"] > current["filed"]
            ):
                deduped[end] = item

        return sorted(
            deduped.values(),
            key=lambda item: item["end"],
            reverse=True,
        )

    @staticmethod
    def _latest_two(
        series: List[Dict[str, Any]],
    ):
        latest = (
            series[0]["value"]
            if len(series) >= 1 else None
        )
        previous = (
            series[1]["value"]
            if len(series) >= 2 else None
        )
        return latest, previous

    @staticmethod
    def _latest_end(
        series: List[Dict[str, Any]],
    ) -> Optional[str]:
        return series[0]["end"] if series else None

    @staticmethod
    def _growth(
        latest: Optional[float],
        previous: Optional[float],
    ) -> Optional[float]:
        if (
            latest is None
            or previous is None
            or previous == 0
        ):
            return None
        return ((latest - previous) / abs(previous)) * 100

    @staticmethod
    def _margin(
        numerator: Optional[float],
        denominator: Optional[float],
    ) -> Optional[float]:
        if numerator is None or not denominator:
            return None
        return (numerator / denominator) * 100

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None
