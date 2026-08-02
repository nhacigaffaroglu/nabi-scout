from __future__ import annotations

from datetime import datetime, timezone

from services.scanner_v3_scoring import score_v3
from services.security_classifier import classify_security


def number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def completeness(fields):
    present = sum(value is not None for value in fields.values())
    return round(present / len(fields) * 100, 1) if fields else 0.0


class ScannerV3Engine:
    def __init__(self, fmp_client, sec_client) -> None:
        self.fmp = fmp_client
        self.sec = sec_client

    def _safe(self, label, callback, fallback):
        try:
            return callback(), "OK", None
        except Exception as exc:
            return fallback, "ERİŞİLEMEDİ", f"{label}: {exc}"

    def analyze(
        self,
        *,
        symbol,
        cik,
        company_name,
        exchange,
        is_etf=False,
        participation_status="Kontrol Et",
        participation_score=60,
        portfolio_fit=55,
    ):
        classification = classify_security(
            symbol=symbol,
            company_name=company_name,
            is_etf=is_etf,
        )

        if not classification["is_investable_common"]:
            return {
                "symbol": symbol,
                "excluded": True,
                "exclude_reason": classification["exclude_reason"],
                "candidate": {
                    "symbol": symbol,
                    "company_name": company_name,
                    "decision": "ELE",
                    "nabi_score": 0.0,
                    "data_completeness": 0.0,
                    "security_type": classification["security_type"],
                    "exclude_reason": classification["exclude_reason"],
                },
                "errors": [],
                "endpoint_status": {},
                "status": "ELENDİ",
            }

        errors = []
        endpoint_status = {}

        profile, endpoint_status["fmp_profile"], error = self._safe(
            "FMP profile",
            lambda: self.fmp.profile(symbol),
            {},
        )
        if error:
            errors.append(error)

        quote, endpoint_status["fmp_quote"], error = self._safe(
            "FMP quote",
            lambda: self.fmp.quote(symbol),
            {},
        )
        if error:
            errors.append(error)

        financials = {}
        if cik:
            payload, endpoint_status["sec_companyfacts"], error = self._safe(
                "SEC Company Facts",
                lambda: self.sec.company_facts(cik),
                {},
            )
            if error:
                errors.append(error)
            elif payload:
                financials = self.sec.extract_financials(payload)
        else:
            errors.append("SEC Company Facts: CIK bulunamadı.")
            endpoint_status["sec_companyfacts"] = "CIK YOK"

        price = number(quote.get("price") or profile.get("price"))
        market_cap = number(
            quote.get("marketCap")
            or profile.get("marketCap")
            or profile.get("mktCap")
        )
        average_volume = number(
            quote.get("avgVolume")
            or quote.get("volume")
            or profile.get("volAvg")
        )
        pe_ratio = number(quote.get("pe"))
        shares = number(
            quote.get("sharesOutstanding")
            or profile.get("sharesOutstanding")
            or financials.get("shares_outstanding_sec")
        )

        revenue = financials.get("revenue")
        equity = financials.get("equity")

        price_to_sales = (
            market_cap / revenue
            if market_cap is not None and revenue
            else None
        )
        price_to_book = (
            market_cap / equity
            if market_cap is not None and equity
            else None
        )

        fields = {
            "price": price,
            "market_cap": market_cap,
            "average_volume": average_volume,
            "revenue": revenue,
            "revenue_growth_1y": financials.get("revenue_growth_1y"),
            "revenue_cagr_3y": financials.get("revenue_cagr_3y"),
            "eps_growth_1y": financials.get("eps_growth_1y"),
            "eps_cagr_3y": financials.get("eps_cagr_3y"),
            "fcf_cagr_3y": financials.get("fcf_cagr_3y"),
            "gross_margin": financials.get("gross_margin"),
            "operating_margin": financials.get("operating_margin"),
            "net_margin": financials.get("net_margin"),
            "fcf_margin": financials.get("free_cash_flow_margin"),
            "roic": financials.get("roic"),
            "roe": financials.get("roe"),
            "roa": financials.get("roa"),
            "current_ratio": financials.get("current_ratio"),
            "debt_to_equity": financials.get("debt_to_equity"),
            "net_debt_to_fcf": financials.get("net_debt_to_fcf"),
            "interest_coverage": financials.get("interest_coverage"),
            "pe_ratio": pe_ratio,
            "price_to_sales": price_to_sales,
            "price_to_book": price_to_book,
            "share_change_3y": financials.get("share_change_3y"),
            "payout_ratio": financials.get("payout_ratio"),
        }
        data_completeness = completeness(fields)

        scores = score_v3(
            revenue_growth_1y=financials.get("revenue_growth_1y"),
            revenue_cagr_3y=financials.get("revenue_cagr_3y"),
            eps_growth_1y=financials.get("eps_growth_1y"),
            eps_cagr_3y=financials.get("eps_cagr_3y"),
            fcf_cagr_3y=financials.get("fcf_cagr_3y"),
            gross_margin=financials.get("gross_margin"),
            operating_margin=financials.get("operating_margin"),
            net_margin=financials.get("net_margin"),
            fcf_margin=financials.get("free_cash_flow_margin"),
            roic=financials.get("roic"),
            roe=financials.get("roe"),
            roa=financials.get("roa"),
            current_ratio=financials.get("current_ratio"),
            debt_to_equity=financials.get("debt_to_equity"),
            net_debt_to_fcf=financials.get("net_debt_to_fcf"),
            interest_coverage=financials.get("interest_coverage"),
            pe_ratio=pe_ratio,
            price_to_sales=price_to_sales,
            price_to_book=price_to_book,
            share_change_3y=financials.get("share_change_3y"),
            payout_ratio=financials.get("payout_ratio"),
            market_cap=market_cap,
            average_volume=average_volume,
            portfolio_fit=portfolio_fit,
            participation_score=participation_score,
            participation_status=participation_status,
            completeness=data_completeness,
        )

        candidate = {
            "symbol": symbol,
            "company_name": (
                profile.get("companyName")
                or quote.get("name")
                or company_name
                or symbol
            ),
            "asset_type": "Hisse",
            "security_type": classification["security_type"],
            "market": "ABD",
            "exchange_name": exchange,
            "currency": (
                profile.get("currency")
                or quote.get("currency")
                or "USD"
            ),
            "country": profile.get("country") or "US",
            "sector_theme": (
                profile.get("sector")
                or profile.get("industry")
            ),
            "participation_status": participation_status,
            "participation_score": participation_score,
            "research_status": "Scanner v3 tarandı",
            "current_price": price,
            "market_cap": market_cap,
            "average_volume": average_volume,
            "shares_outstanding": shares,
            "revenue": revenue,
            "revenue_growth": financials.get("revenue_growth_1y"),
            "revenue_cagr_3y": financials.get("revenue_cagr_3y"),
            "eps_growth": financials.get("eps_growth_1y"),
            "eps_cagr_3y": financials.get("eps_cagr_3y"),
            "fcf_cagr_3y": financials.get("fcf_cagr_3y"),
            "gross_margin": financials.get("gross_margin"),
            "operating_margin": financials.get("operating_margin"),
            "net_margin": financials.get("net_margin"),
            "free_cash_flow": financials.get("free_cash_flow"),
            "free_cash_flow_margin": financials.get(
                "free_cash_flow_margin"
            ),
            "roic": financials.get("roic"),
            "roe": financials.get("roe"),
            "roa": financials.get("roa"),
            "net_debt": financials.get("net_debt"),
            "net_debt_to_fcf": financials.get("net_debt_to_fcf"),
            "current_ratio": financials.get("current_ratio"),
            "debt_to_equity": financials.get("debt_to_equity"),
            "interest_coverage": financials.get("interest_coverage"),
            "pe_ratio": pe_ratio,
            "price_to_sales": price_to_sales,
            "price_to_book": price_to_book,
            "share_change_3y": financials.get("share_change_3y"),
            "payout_ratio": financials.get("payout_ratio"),
            "quality_score": scores["quality_score"],
            "growth_score": scores["growth_score"],
            "valuation_score": scores["valuation_score"],
            "financial_health_score": scores[
                "financial_health_score"
            ],
            "capital_allocation_score": scores[
                "capital_allocation_score"
            ],
            "risk_score": scores["risk_score"],
            "portfolio_fit_score": portfolio_fit,
            "liquidity_score": scores["liquidity_score"],
            "nabi_score": scores["nabi_score"],
            "decision": scores["decision"],
            "data_completeness": data_completeness,
            "data_source": "SEC Company Facts + FMP",
            "source_updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "collector_notes": " | ".join(errors) if errors else None,
            "source_url": profile.get("website"),
            "notes": profile.get("description"),
            "cik": cik,
            "financial_period_end": financials.get(
                "financial_period_end"
            ),
            "annual_periods_found": financials.get(
                "annual_periods_found"
            ),
            "scanner_version": "Scanner v3",
            "exclude_reason": None,
        }

        return {
            "symbol": symbol,
            "excluded": False,
            "candidate": candidate,
            "endpoint_status": endpoint_status,
            "errors": errors,
            "status": (
                "TAM VERİ"
                if data_completeness >= 85
                else "YETERLİ VERİ"
                if data_completeness >= 65
                else "KISMİ VERİ"
            ),
        }
