from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


class SECFinancialError(RuntimeError):
    pass


_ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}

_US_GAAP_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_cash": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ],
    "eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
    ],
    "shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "interest_expense": [
        "InterestExpenseNonOperating",
        "InterestAndDebtExpense",
        "InterestExpense",
    ],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
    "dividends": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "assets": ["Assets"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
    ],
}

_IFRS_TAGS = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "net_income": [
        "ProfitLoss",
        "ProfitLossAttributableToOwnersOfParent",
    ],
    "operating_income": [
        "ProfitLossFromOperatingActivities",
        "OperatingProfitLoss",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_cash": [
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFromUsedInOperatingActivities",
    ],
    "capex": [
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "eps": [
        "DilutedEarningsLossPerShare",
        "BasicAndDilutedEarningsLossPerShare",
        "BasicEarningsLossPerShare",
    ],
    "shares": [
        "WeightedAverageShares",
        "AdjustedWeightedAverageShares",
    ],
    "interest_expense": [
        "FinanceCosts",
        "InterestExpenseOnBorrowings",
    ],
    "pretax_income": ["ProfitLossBeforeTax"],
    "tax_expense": [
        "IncomeTaxExpenseContinuingOperations",
        "IncomeTaxExpense",
    ],
    "dividends": ["DividendsPaid"],
    "assets": ["Assets"],
    "equity": ["Equity", "EquityAttributableToOwnersOfParent"],
    "cash": ["CashAndCashEquivalents"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "accounts_receivable": [
        "TradeAndOtherCurrentReceivables",
        "TradeReceivables",
    ],
}

# Exclusive total-debt concepts. First tag present at the assets period wins.
# Never combine a total with component debt tags.
_US_GAAP_DEBT_TOTAL_PRECEDENCE: Sequence[str] = (
    "DebtAndCapitalLeaseObligations",
    "DebtLongtermAndShorttermCombinedAmount",
)

# Exclusive current-debt group. First tag present at the assets period wins.
_US_GAAP_DEBT_CURRENT_PRECEDENCE: Sequence[str] = (
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtCurrent",
    "DebtCurrent",
)

# Exclusive noncurrent-debt group. First tag present at the assets period wins.
_US_GAAP_DEBT_NONCURRENT_PRECEDENCE: Sequence[str] = (
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtNoncurrent",
    "LongTermDebt",
)

_US_GAAP_SHORT_TERM_BORROWINGS_TAG = "ShortTermBorrowings"

_IFRS_DEBT_TAGS = [
    "CurrentPortionOfLongtermBorrowings",
    "ShorttermBorrowings",
    "LongtermBorrowings",
]

_US_GAAP_INTEREST_BEARING_SECURITIES_TAG_TIERS: Sequence[Sequence[str]] = (
    (
        "MarketableSecuritiesCurrent",
        "MarketableSecuritiesNoncurrent",
    ),
    ("MarketableSecurities",),
    (
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
    ),
    (
        "AvailableForSaleSecuritiesDebtSecurities",
        "ShortTermInvestments",
        "DebtSecuritiesAvailableForSaleAmortizedCost",
        "AvailableForSaleSecurities",
    ),
)

_US_GAAP_INTEREST_BEARING_SECURITIES_TAGS = [
    tag
    for tier in _US_GAAP_INTEREST_BEARING_SECURITIES_TAG_TIERS
    for tag in tier
]

_IFRS_INTEREST_BEARING_SECURITIES_TAGS = [
    "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
    "FinancialAssetsAtFairValueThroughProfitOrLoss",
    "OtherCurrentFinancialAssets",
]


class SECFinancialClient:
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
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
        self._submissions_cache: Dict[str, Dict[str, Any]] = {}

    def company_submissions(self, cik: int | str) -> Dict[str, Any]:
        cik_text = str(cik).strip().zfill(10)
        cached = self._submissions_cache.get(cik_text)
        if cached is not None:
            return cached
        try:
            response = self.session.get(
                self.SUBMISSIONS_URL.format(cik=cik_text),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SECFinancialError(
                "SEC Submissions bağlantı hatası."
            ) from exc

        if response.status_code == 404:
            raise SECFinancialError(
                f"SEC Submissions bulunamadı: CIK {cik_text}"
            )
        if response.status_code != 200:
            raise SECFinancialError(
                f"SEC Submissions HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SECFinancialError(
                "SEC Submissions geçerli JSON döndürmedi."
            ) from exc
        self._submissions_cache[cik_text] = payload
        return payload

    @staticmethod
    def extract_entity_metadata_from_submissions(
        payload: Dict[str, Any],
    ) -> Dict[str, Optional[str]]:
        sic = payload.get("sic")
        sic_description = payload.get("sicDescription") or payload.get("sic_description")
        return {
            "sic_code": str(sic).strip() if sic not in (None, "") else None,
            "sic_description": str(sic_description).strip()
            if sic_description not in (None, "")
            else None,
            "entity_name": str(payload.get("name") or payload.get("entityName") or "").strip()
            or None,
        }

    def resolve_entity_metadata(
        self,
        company_facts_payload: Dict[str, Any],
        *,
        cik: Optional[int | str] = None,
    ) -> Tuple[Dict[str, Optional[str]], Tuple[Tuple[str, str], ...]]:
        metadata = self.extract_entity_metadata(company_facts_payload)
        evidence: list[tuple[str, str]] = [("metadata_source", "sec_company_facts")]
        if metadata.get("sic_code"):
            evidence.append(("sic_source", "sec_company_facts"))
            return metadata, tuple(evidence)

        if cik is None:
            return metadata, tuple(evidence)

        try:
            submissions = self.company_submissions(cik)
        except SECFinancialError:
            return metadata, tuple(evidence)

        submission_metadata = self.extract_entity_metadata_from_submissions(submissions)
        if submission_metadata.get("sic_code"):
            metadata = {
                **metadata,
                "sic_code": submission_metadata["sic_code"],
                "sic_description": submission_metadata.get("sic_description")
                or metadata.get("sic_description"),
                "entity_name": metadata.get("entity_name")
                or submission_metadata.get("entity_name"),
            }
            evidence.append(("sic_source", "sec_submissions"))
        return metadata, tuple(evidence)

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

    @staticmethod
    def extract_entity_metadata(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
        sic = payload.get("sic")
        sic_description = payload.get("sicDescription") or payload.get("sic_description")
        return {
            "sic_code": str(sic).strip() if sic not in (None, "") else None,
            "sic_description": str(sic_description).strip()
            if sic_description not in (None, "")
            else None,
            "entity_name": str(payload.get("entityName") or "").strip() or None,
        }

    def extract_financials(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:
        taxonomy, facts, currency = self._resolve_facts(payload)
        if not facts or not currency:
            return self._empty_financials(taxonomy)

        tag_map = (
            _US_GAAP_TAGS
            if taxonomy == "us-gaap"
            else _IFRS_TAGS
        )
        monetary_units = [currency]
        eps_units = [
            f"{currency}/shares",
            f"{currency} / shares",
        ]
        share_units = ["shares"]

        revenue = self._annual_series(
            facts,
            tag_map["revenue"],
            monetary_units,
        )
        net_income = self._annual_series(
            facts,
            tag_map["net_income"],
            monetary_units,
        )
        operating_income = self._annual_series(
            facts,
            tag_map["operating_income"],
            monetary_units,
        )
        gross_profit = self._annual_series(
            facts,
            tag_map["gross_profit"],
            monetary_units,
        )
        operating_cash = self._annual_series(
            facts,
            tag_map["operating_cash"],
            monetary_units,
        )
        capex = self._annual_series(
            facts,
            tag_map["capex"],
            monetary_units,
        )
        eps = self._annual_series(
            facts,
            tag_map["eps"],
            eps_units,
        )
        shares = self._annual_series(
            facts,
            tag_map["shares"],
            share_units,
        )
        interest_expense = self._annual_series(
            facts,
            tag_map["interest_expense"],
            monetary_units,
        )
        pretax_income = self._annual_series(
            facts,
            tag_map["pretax_income"],
            monetary_units,
        )
        tax_expense = self._annual_series(
            facts,
            tag_map["tax_expense"],
            monetary_units,
        )
        dividends = self._annual_series(
            facts,
            tag_map["dividends"],
            monetary_units,
        )

        assets = self._instant_series(
            facts,
            tag_map["assets"],
            monetary_units,
        )
        equity = self._instant_series(
            facts,
            tag_map["equity"],
            monetary_units,
        )
        cash = self._instant_series(
            facts,
            tag_map["cash"],
            monetary_units,
        )
        current_assets = self._instant_series(
            facts,
            tag_map["current_assets"],
            monetary_units,
        )
        current_liabilities = self._instant_series(
            facts,
            tag_map["current_liabilities"],
            monetary_units,
        )
        accounts_receivable = self._instant_series(
            facts,
            tag_map["accounts_receivable"],
            monetary_units,
        )

        latest = lambda series: self._value(series, 0)
        balance_sheet_end = assets[0]["end"] if assets else None

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

        assets_latest = self._aligned_instant_value(assets, balance_sheet_end)
        equity_latest, _ = self._period_aligned_instant(
            facts,
            tag_map["equity"],
            monetary_units,
            period_end=balance_sheet_end,
            fallback_series=equity,
        )
        cash_latest, cash_tags = self._period_aligned_instant(
            facts,
            tag_map["cash"],
            monetary_units,
            period_end=balance_sheet_end,
            fallback_series=cash,
        )
        current_assets_latest, _ = self._period_aligned_instant(
            facts,
            tag_map["current_assets"],
            monetary_units,
            period_end=balance_sheet_end,
            fallback_series=current_assets,
        )
        current_liabilities_latest, _ = self._period_aligned_instant(
            facts,
            tag_map["current_liabilities"],
            monetary_units,
            period_end=balance_sheet_end,
            fallback_series=current_liabilities,
        )
        accounts_receivable_latest, accounts_receivable_tags = self._period_aligned_instant(
            facts,
            tag_map["accounts_receivable"],
            monetary_units,
            period_end=balance_sheet_end,
            fallback_series=accounts_receivable,
        )
        debt_latest, debt_tags = self._debt_at_end(
            facts,
            monetary_units,
            taxonomy=taxonomy,
            period_end=balance_sheet_end,
        )
        (
            interest_bearing_securities_latest,
            interest_bearing_securities_tags,
        ) = self._interest_bearing_securities_at_end(
            facts,
            monetary_units,
            taxonomy=taxonomy,
            period_end=balance_sheet_end,
        )

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

        prior_period_end = revenue[1]["end"] if len(revenue) > 1 else None
        prior_payload: dict[str, Any] = {}
        if prior_period_end:
            prior_payload = {
                "comparison_period_end": prior_period_end,
                "revenue_prior": self._value(revenue, 1),
                "eps_prior": self._value(eps, 1),
                "operating_income_prior": self._value(operating_income, 1),
                "net_income_prior": self._value(net_income, 1),
                "operating_cash_flow_prior": self._value(operating_cash, 1),
                "capital_expenditure_prior": self._value(capex, 1),
                "total_assets_prior": self._aligned_instant_value(assets, prior_period_end),
                "cash_prior": self._period_aligned_instant(
                    facts,
                    tag_map["cash"],
                    monetary_units,
                    period_end=prior_period_end,
                    fallback_series=cash,
                )[0],
                "total_debt_prior": self._debt_at_end(
                    facts,
                    monetary_units,
                    taxonomy=taxonomy,
                    period_end=prior_period_end,
                )[0],
                "gross_profit_prior": self._value(gross_profit, 1),
            }
            prior_ocf = prior_payload.get("operating_cash_flow_prior")
            prior_capex = prior_payload.get("capital_expenditure_prior")
            if prior_ocf is not None and prior_capex is not None:
                prior_payload["free_cash_flow_prior"] = prior_ocf - abs(prior_capex)

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
            "operating_income": operating_income_latest,
            "net_income": net_income_latest,
            "nopat": nopat,
            "invested_capital": invested_capital,
            "tax_rate": tax_rate,
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
            "cash_tags": cash_tags,
            "accounts_receivable": accounts_receivable_latest,
            "accounts_receivable_tags": accounts_receivable_tags,
            "interest_bearing_securities": interest_bearing_securities_latest,
            "interest_bearing_securities_tags": interest_bearing_securities_tags,
            "balance_sheet_period_end": balance_sheet_end,
            "total_debt": debt_latest,
            "total_debt_tags": debt_tags,
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
            "financial_currency": currency,
            "financial_taxonomy": taxonomy,
            **prior_payload,
        }

    def _resolve_facts(
        self,
        payload: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any], Optional[str]]:
        all_facts = payload.get("facts", {})

        us_gaap = all_facts.get("us-gaap", {})
        if us_gaap:
            currency = self._detect_currency(us_gaap, "us-gaap")
            if currency:
                return "us-gaap", us_gaap, currency

        ifrs = all_facts.get("ifrs-full", {})
        if ifrs:
            currency = self._detect_currency(ifrs, "ifrs-full")
            if currency:
                return "ifrs-full", ifrs, currency

        return "us-gaap", us_gaap, None

    def _detect_currency(
        self,
        facts: Dict[str, Any],
        taxonomy: str,
    ) -> Optional[str]:
        tag_map = (
            _US_GAAP_TAGS
            if taxonomy == "us-gaap"
            else _IFRS_TAGS
        )

        for tag in tag_map["revenue"]:
            unit_map = facts.get(tag, {}).get("units", {})
            if not unit_map:
                continue

            if taxonomy == "us-gaap" and "USD" in unit_map:
                if self._has_annual_entries(unit_map["USD"]):
                    return "USD"

            for unit in sorted(unit_map):
                if unit in {"shares", "pure"} or "/shares" in unit:
                    continue
                if self._has_annual_entries(unit_map[unit]):
                    return unit.split("/")[0]

        return None

    @staticmethod
    def _has_annual_entries(entries: Sequence[Dict[str, Any]]) -> bool:
        for item in entries:
            if item.get("form") not in _ANNUAL_FORMS:
                continue
            start = item.get("start")
            end = item.get("end")
            if not start or not end:
                continue
            try:
                days = (
                    date.fromisoformat(end)
                    - date.fromisoformat(start)
                ).days
            except ValueError:
                continue
            if 300 <= days <= 430:
                return True
        return False

    @staticmethod
    def _empty_financials(taxonomy: str) -> Dict[str, Optional[float]]:
        return {
            "revenue": None,
            "financial_period_end": None,
            "annual_periods_found": 0,
            "financial_currency": None,
            "financial_taxonomy": taxonomy,
        }

    def _annual_series(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
    ) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []

        for tag in tags:
            entries = self._entries(facts, tag, units)

            for item in entries:
                if item.get("form") not in _ANNUAL_FORMS:
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

        return self._dedupe(selected)

    def _instant_series(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
    ) -> List[Dict[str, Any]]:
        for tag in tags:
            selected = []
            for item in self._entries(facts, tag, units):
                if item.get("form") not in _ANNUAL_FORMS:
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

    def _first_tag_value_at_period(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
        period_end: str,
    ) -> Tuple[Optional[float], Optional[str]]:
        for tag in tags:
            value = self._tag_value_at_period_end(
                facts,
                tag,
                units,
                period_end,
            )
            if value is not None:
                return value, tag
        return None, None

    def _period_aligned_instant(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
        *,
        period_end: Optional[str],
        fallback_series: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[float], Optional[str]]:
        if period_end:
            return self._first_tag_value_at_period(
                facts,
                tags,
                units,
                period_end,
            )
        if fallback_series:
            return fallback_series[0].get("value"), None
        return None, None

    def _exclusive_group_value_at_end(
        self,
        facts: Dict[str, Any],
        tags: Sequence[str],
        units: Sequence[str],
        period_end: str,
    ) -> Tuple[Optional[float], Optional[str]]:
        return self._first_tag_value_at_period(facts, tags, units, period_end)

    def _debt_at_end(
        self,
        facts: Dict[str, Any],
        units: Sequence[str],
        *,
        taxonomy: str,
        period_end: Optional[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        if not period_end:
            return None, None

        if taxonomy != "us-gaap":
            values: List[float] = []
            used_tags: List[str] = []
            for tag in _IFRS_DEBT_TAGS:
                value = self._tag_value_at_period_end(
                    facts,
                    tag,
                    units,
                    period_end,
                )
                if value is not None:
                    values.append(value)
                    used_tags.append(tag)
            if not values:
                return None, None
            return sum(values), "+".join(used_tags)

        total_value, total_tag = self._exclusive_group_value_at_end(
            facts,
            _US_GAAP_DEBT_TOTAL_PRECEDENCE,
            units,
            period_end,
        )
        if total_value is not None and total_tag:
            return total_value, total_tag

        current_value, current_tag = self._exclusive_group_value_at_end(
            facts,
            _US_GAAP_DEBT_CURRENT_PRECEDENCE,
            units,
            period_end,
        )
        noncurrent_value, noncurrent_tag = self._exclusive_group_value_at_end(
            facts,
            _US_GAAP_DEBT_NONCURRENT_PRECEDENCE,
            units,
            period_end,
        )

        used_tags: List[str] = []
        total = 0.0
        found = False
        if current_value is not None and current_tag:
            total += current_value
            used_tags.append(current_tag)
            found = True
        if noncurrent_value is not None and noncurrent_tag:
            total += noncurrent_value
            used_tags.append(noncurrent_tag)
            found = True

        short_term_already_in_current = current_tag == "DebtCurrent"
        if not short_term_already_in_current:
            stb_value = self._tag_value_at_period_end(
                facts,
                _US_GAAP_SHORT_TERM_BORROWINGS_TAG,
                units,
                period_end,
            )
            if stb_value is not None:
                total += stb_value
                used_tags.append(_US_GAAP_SHORT_TERM_BORROWINGS_TAG)
                found = True

        if not found:
            return None, None
        return total, "+".join(used_tags)

    @staticmethod
    def _aligned_instant_value(
        series: List[Dict[str, Any]],
        period_end: Optional[str],
    ) -> Optional[float]:
        if not series:
            return None
        if period_end:
            for row in series:
                if row.get("end") == period_end:
                    return row.get("value")
            return None
        return series[0].get("value")

    def _tag_value_at_period_end(
        self,
        facts: Dict[str, Any],
        tag: str,
        units: Sequence[str],
        period_end: str,
    ) -> Optional[float]:
        selected: List[Dict[str, Any]] = []
        for item in self._entries(facts, tag, units):
            if item.get("form") not in _ANNUAL_FORMS:
                continue
            end = item.get("end")
            value = self._number(item.get("val"))
            if end != period_end or value is None:
                continue
            selected.append({
                "value": value,
                "end": end,
                "filed": item.get("filed") or "",
            })
        deduped = self._dedupe(selected)
        return deduped[0]["value"] if deduped else None

    def _interest_bearing_securities_at_end(
        self,
        facts: Dict[str, Any],
        units: Sequence[str],
        *,
        taxonomy: str,
        period_end: Optional[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        if not period_end:
            return None, None

        if taxonomy == "us-gaap":
            tiers = _US_GAAP_INTEREST_BEARING_SECURITIES_TAG_TIERS
        else:
            tiers = (_IFRS_INTEREST_BEARING_SECURITIES_TAGS,)

        for tier in tiers:
            values: List[float] = []
            used_tags: List[str] = []
            for tag in tier:
                value = self._tag_value_at_period_end(
                    facts,
                    tag,
                    units,
                    period_end,
                )
                if value is not None:
                    values.append(value)
                    used_tags.append(tag)
            if not values:
                continue
            if len(tier) == 1:
                return values[0], tier[0]
            return sum(values), "+".join(used_tags)

        return None, None

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
