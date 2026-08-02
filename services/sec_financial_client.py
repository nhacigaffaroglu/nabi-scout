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
        try:
            response = self.session.get(
                f"{self.BASE_URL}/CIK{cik_text}.json",
                timeout=self.timeout,
            )
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
        facts = payload.get("facts", {}).get("us-gaap", {})

        revenue = self._annual_series(
            facts,
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ],
            ["USD"],
        )
        net_income = self._annual_series(
            facts,
            ["NetIncomeLoss", "ProfitLoss"],
            ["USD"],
        )
        operating_income = self._annual_series(
            facts,
            ["OperatingIncomeLoss"],
            ["USD"],
        )
        gross_profit = self._annual_series(
            facts,
            ["GrossProfit"],
            ["USD"],
        )
        operating_cash = self._annual_series(
            facts,
            [
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ],
            ["USD"],
        )
        capex = self._annual_series(
            facts,
            [
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsForAdditionsToPropertyPlantAndEquipment",
            ],
            ["USD"],
        )
        eps = self._annual_series(
            facts,
            [
                "EarningsPerShareDiluted",
                "EarningsPerShareBasicAndDiluted",
            ],
            ["USD/shares", "USD / shares"],
        )
        shares = self._annual_series(
            facts,
            [
                "WeightedAverageNumberOfDilutedSharesOutstanding",
                "WeightedAverageNumberOfSharesOutstandingBasic",
            ],
            ["shares"],
        )
        interest_expense = self._annual_series(
            facts,
            [
                "InterestExpenseNonOperating",
                "InterestAndDebtExpense",
                "InterestExpense",
            ],
            ["USD"],
        )
        pretax_income = self._annual_series(
            facts,
            [
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ],
            ["USD"],
        )
        tax_expense = self._annual_series(
            facts,
            ["IncomeTaxExpenseBenefit"],
            ["USD"],
        )
        dividends = self._annual_series(
            facts,
            [
                "PaymentsOfDividends",
                "PaymentsOfDividendsCommonStock",
            ],
            ["USD"],
        )

        assets = self._instant_series(facts, ["Assets"], ["USD"])
        equity = self._instant_series(
            facts,
            [
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ],
            ["USD"],
        )
        cash = self._instant_series(
            facts,
            [
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ],
            ["USD"],
        )
        current_assets = self._instant_series(
            facts,
            ["AssetsCurrent"],
            ["USD"],
        )
        current_liabilities = self._instant_series(
            facts,
            ["LiabilitiesCurrent"],
            ["USD"],
        )
        debt = self._debt_series(facts)

        latest = lambda series: self._value(series, 0)

        revenue_latest = latest(revenue)
        net_income_latest = latest(net_income)
        operating_income_latest = latest(operating_income)
        gross_profit_latest = latest(gross_profit)
        operating_cash_latest = latest(operating_cash)
        capex_latest = latest(capex)
        eps_latest = latest(eps)
        shares_latest = latest(shares)
        interest_latest = latest(interest_expense)
        pretax_latest = latest(pretax_income)
        tax_latest = latest(tax_expense)
        dividends_latest = latest(dividends)

        assets_latest = latest(assets)
        equity_latest = latest(equity)
        cash_latest = latest(cash)
        current_assets_latest = latest(current_assets)
        current_liabilities_latest = latest(current_liabilities)
        debt_latest = latest(debt)

        free_cash_flow = (
            operating_cash_latest - abs(capex_latest or 0)
            if operating_cash_latest is not None
            else None
        )

        current_ratio = (
            current_assets_latest / current_liabilities_latest
            if current_assets_latest is not None
            and current_liabilities_latest
            else None
        )
        debt_to_equity = (
            debt_latest / equity_latest
            if debt_latest is not None and equity_latest
            else None
        )
        net_debt = (
            debt_latest - (cash_latest or 0)
            if debt_latest is not None
            else None
        )
        net_debt_to_fcf = (
            net_debt / free_cash_flow
            if net_debt is not None
            and free_cash_flow
            and free_cash_flow > 0
            else None
        )
        interest_coverage = (
            operating_income_latest / abs(interest_latest)
            if operating_income_latest is not None
            and interest_latest
            else None
        )

        tax_rate = 0.21
        if pretax_latest and tax_latest is not None:
            candidate_tax_rate = tax_latest / pretax_latest
            if 0 <= candidate_tax_rate <= 0.5:
                tax_rate = candidate_tax_rate

        invested_capital = (
            equity_latest
            + (debt_latest or 0)
            - (cash_latest or 0)
            if equity_latest is not None
            else None
        )
        nopat = (
            operating_income_latest * (1 - tax_rate)
            if operating_income_latest is not None
            else None
        )
        roic = (
            nopat / invested_capital * 100
            if nopat is not None and invested_capital
            else None
        )
        roe = (
            net_income_latest / equity_latest * 100
            if net_income_latest is not None and equity_latest
            else None
        )
        roa = (
            net_income_latest / assets_latest * 100
            if net_income_latest is not None and assets_latest
            else None
        )

        payout_ratio = (
            abs(dividends_latest) / net_income_latest * 100
            if dividends_latest is not None
            and net_income_latest
            and net_income_latest > 0
            else None
        )

        share_change_3y = self._change(shares, 3)

        return {
            "revenue": revenue_latest,
            "revenue_growth_1y": self._growth(revenue, 1),
            "revenue_cagr_3y": self._cagr(revenue, 3),
            "eps": eps_latest,
            "eps_growth_1y": self._growth(eps, 1),
            "eps_cagr_3y": self._cagr(eps, 3),
            "gross_margin": self._margin(
                gross_profit_latest,
                revenue_latest,
            ),
            "operating_margin": self._margin(
                operating_income_latest,
                revenue_latest,
            ),
            "net_margin": self._margin(
                net_income_latest,
                revenue_latest,
            ),
            "operating_cash_flow": operating_cash_latest,
            "capital_expenditure": capex_latest,
            "free_cash_flow": free_cash_flow,
            "free_cash_flow_margin": self._margin(
                free_cash_flow,
                revenue_latest,
            ),
            "fcf_cagr_3y": self._derived_fcf_cagr(
                operating_cash,
                capex,
                years=3,
            ),
            "total_assets": assets_latest,
            "equity": equity_latest,
            "cash": cash_latest,
            "total_debt": debt_latest,
            "net_debt": net_debt,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "net_debt_to_fcf": net_debt_to_fcf,
            "interest_coverage": interest_coverage,
            "roic": roic,
            "roe": roe,
            "roa": roa,
            "shares_outstanding_sec": shares_latest,
            "share_change_3y": share_change_3y,
            "payout_ratio": payout_ratio,
            "financial_period_end": (
                revenue[0]["end"] if revenue else None
            ),
            "annual_periods_found": len(revenue),
        }

    def _annual_series(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
    ) -> List[Dict[str, Any]]:
        for tag in tags:
            entries = self._entries(facts, tag, units)
            selected = []

            for item in entries:
                if item.get("form") not in {
                    "10-K",
                    "10-K/A",
                    "20-F",
                    "40-F",
                }:
                    continue

                start = item.get("start")
                end = item.get("end")
                value = self._number(item.get("val"))
                if not start or not end or value is None:
                    continue

                try:
                    days = (
                        date.fromisoformat(end)
                        - date.fromisoformat(start)
                    ).days
                except ValueError:
                    continue

                if 300 <= days <= 430:
                    selected.append({
                        "value": value,
                        "end": end,
                        "filed": item.get("filed") or "",
                    })

            result = self._dedupe(selected)
            if result:
                return result

        return []

    def _instant_series(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
    ) -> List[Dict[str, Any]]:
        for tag in tags:
            selected = []
            for item in self._entries(facts, tag, units):
                if item.get("form") not in {
                    "10-K",
                    "10-K/A",
                    "20-F",
                    "40-F",
                }:
                    continue

                end = item.get("end")
                value = self._number(item.get("val"))
                if not end or value is None:
                    continue

                selected.append({
                    "value": value,
                    "end": end,
                    "filed": item.get("filed") or "",
                })

            result = self._dedupe(selected)
            if result:
                return result

        return []

    def _debt_series(
        self,
        facts: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        tags = [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "ShortTermBorrowings",
            "LongTermDebtNoncurrent",
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        ]
        by_end: Dict[str, Dict[str, Any]] = {}

        for tag in tags:
            for item in self._entries(facts, tag, ["USD"]):
                if item.get("form") not in {
                    "10-K",
                    "10-K/A",
                    "20-F",
                    "40-F",
                }:
                    continue

                end = item.get("end")
                value = self._number(item.get("val"))
                if not end or value is None:
                    continue

                row = by_end.setdefault(
                    end,
                    {
                        "value": 0.0,
                        "end": end,
                        "filed": "",
                    },
                )
                row["value"] += value
                row["filed"] = max(
                    row["filed"],
                    item.get("filed") or "",
                )

        return sorted(
            by_end.values(),
            key=lambda row: row["end"],
            reverse=True,
        )

    def _derived_fcf_cagr(
        self,
        operating_cash: List[Dict[str, Any]],
        capex: List[Dict[str, Any]],
        *,
        years: int,
    ) -> Optional[float]:
        by_end = {
            item["end"]: item["value"]
            for item in operating_cash
        }
        capex_by_end = {
            item["end"]: item["value"]
            for item in capex
        }

        series = []
        for end, ocf in by_end.items():
            fcf = ocf - abs(capex_by_end.get(end, 0))
            series.append({
                "end": end,
                "value": fcf,
            })

        series = sorted(
            series,
            key=lambda row: row["end"],
            reverse=True,
        )
        return self._cagr(series, years)

    @staticmethod
    def _entries(
        facts: Dict[str, Any],
        tag: str,
        units: Sequence[str],
    ) -> List[Dict[str, Any]]:
        unit_map = facts.get(tag, {}).get("units", {})
        for unit in units:
            if unit in unit_map:
                return unit_map[unit]
        return []

    @staticmethod
    def _dedupe(
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_end: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            current = by_end.get(row["end"])
            if current is None or row["filed"] > current["filed"]:
                by_end[row["end"]] = row

        return sorted(
            by_end.values(),
            key=lambda row: row["end"],
            reverse=True,
        )

    @staticmethod
    def _value(
        series: List[Dict[str, Any]],
        index: int,
    ) -> Optional[float]:
        return (
            series[index]["value"]
            if len(series) > index
            else None
        )

    def _growth(
        self,
        series: List[Dict[str, Any]],
        years_back: int,
    ) -> Optional[float]:
        latest = self._value(series, 0)
        previous = self._value(series, years_back)
        if latest is None or previous is None or previous == 0:
            return None
        return (latest - previous) / abs(previous) * 100

    def _change(
        self,
        series: List[Dict[str, Any]],
        years_back: int,
    ) -> Optional[float]:
        return self._growth(series, years_back)

    def _cagr(
        self,
        series: List[Dict[str, Any]],
        years: int,
    ) -> Optional[float]:
        latest = self._value(series, 0)
        previous = self._value(series, years)

        if (
            latest is None
            or previous is None
            or latest <= 0
            or previous <= 0
        ):
            return None

        return ((latest / previous) ** (1 / years) - 1) * 100

    @staticmethod
    def _margin(
        numerator: Optional[float],
        denominator: Optional[float],
    ) -> Optional[float]:
        if numerator is None or not denominator:
            return None
        return numerator / denominator * 100

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None
