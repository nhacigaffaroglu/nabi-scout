from __future__ import annotations

from datetime import datetime, timezone

from services.fmp_client import FMPError
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.security_classifier import classify_security


def number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def completeness(fields):
    if not fields:
        return 0.0
    present = sum(value is not None for value in fields.values())
    return round(present / len(fields) * 100, 1)


class ScannerV4Engine:
    def __init__(self, fmp_client, sec_client) -> None:
        self.fmp = fmp_client
        self.sec = sec_client

    def _endpoint_status_from_error(self, exc: Exception) -> str:
        if isinstance(exc, FMPError):
            mapping = {
                "rate_limit": "RATE_LIMIT",
                "plan_restricted": "PLAN_RESTRICTED",
                "auth": "AUTH_ERROR",
                "timeout": "TIMEOUT",
                "network": "NETWORK_ERROR",
                "not_found": "NOT_FOUND",
                "transient_http": "SERVER_ERROR",
                "http_error": "SERVER_ERROR",
                "malformed": "MALFORMED",
                "empty": "EMPTY",
            }
            return mapping.get(exc.error_class, "ERİŞİLEMEDİ")
        return "ERİŞİLEMEDİ"

    def _safe(self, label, callback, fallback):
        try:
            return callback(), "OK", None
        except FMPError as exc:
            status = self._endpoint_status_from_error(exc)
            return fallback, status, f"{label}: {exc}"
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
            candidate = {
                "symbol": symbol,
                "company_name": company_name,
                "decision": "ELE",
                "nabi_score": 0.0,
                "data_completeness": 0.0,
                "security_type": classification["security_type"],
                "exclude_reason": classification["exclude_reason"],
                "investment_profile": "ELENDİ",
                "score_confidence": "YÜKSEK",
                "scanner_version": "Scanner v4",
            }
            return {
                "symbol": symbol,
                "excluded": True,
                "exclude_reason": classification["exclude_reason"],
                "candidate": candidate,
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
            endpoint_status["sec_companyfacts"] = "CIK YOK"
            errors.append("SEC Company Facts: CIK bulunamadı.")

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
        pe_source = "quote" if pe_ratio is not None else None
        ratios_unavailable = False
        if pe_ratio is None:
            ratios, endpoint_status["fmp_ratios_ttm"], error = self._safe(
                "FMP ratios_ttm",
                lambda: self.fmp.ratios_ttm(symbol),
                {},
            )
            if error:
                errors.append(error)
                if endpoint_status["fmp_ratios_ttm"] != "OK":
                    ratios_unavailable = True
            elif ratios:
                pe_ratio = number(
                    ratios.get("priceToEarningsRatioTTM")
                    or ratios.get("priceToEarningsDilutedRatioTTM")
                )
                if pe_ratio is not None:
                    pe_source = "ratios_ttm"
            if pe_ratio is None:
                if ratios_unavailable or any(
                    endpoint_status.get(key) not in (None, "OK")
                    for key in ("fmp_profile", "fmp_quote", "fmp_ratios_ttm")
                ):
                    pe_source = "unavailable"
                else:
                    pe_source = "missing"

        shares = number(
            quote.get("sharesOutstanding")
            or profile.get("sharesOutstanding")
            or financials.get("shares_outstanding_sec")
        )

        revenue = financials.get("revenue")
        equity = financials.get("equity")
        financial_currency = (
            financials.get("financial_currency") or "USD"
        ).upper()
        quote_currency = (
            profile.get("currency")
            or quote.get("currency")
            or "USD"
        ).upper()
        valuation_currency_ok = (
            financial_currency == "USD"
            and quote_currency == "USD"
        )

        price_to_sales = (
            market_cap / revenue
            if valuation_currency_ok
            and market_cap is not None
            and revenue
            else None
        )
        price_to_book = (
            market_cap / equity
            if valuation_currency_ok
            and market_cap is not None
            and equity
            else None
        )

        tracked = {
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
        data_completeness = completeness(tracked)

        score = calculate_nabi_score_v4(
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
            "research_status": "Scanner v4 tarandı",
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
            "free_cash_flow_margin": financials.get("free_cash_flow_margin"),
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
            "profitability_score": score["profitability_score"],
            "capital_efficiency_score": score["capital_efficiency_score"],
            "quality_score": score["quality_score"],
            "growth_score": score["growth_score"],
            "valuation_score": score["valuation_score"],
            "financial_health_score": score["financial_health_score"],
            "shareholder_score": score["shareholder_score"],
            "risk_score": score["risk_score"],
            "portfolio_fit_score": portfolio_fit,
            "liquidity_score": score["liquidity_score"],
            "nabi_score": score["nabi_score"],
            "decision": score["decision"],
            "investment_profile": score["investment_profile"],
            "score_confidence": score["score_confidence"],
            "score_penalty": score["score_penalty"],
            "hard_flags": score["hard_flags"],
            "positive_reasons": score["positive_reasons"],
            "negative_reasons": score["negative_reasons"],
            "score_reasons": score["all_reasons"],
            "data_completeness": data_completeness,
            "data_source": "SEC Company Facts + FMP",
            "source_updated_at": datetime.now(timezone.utc).isoformat(),
            "collector_notes": " | ".join(errors) if errors else None,
            "source_url": profile.get("website"),
            "notes": profile.get("description"),
            "cik": cik,
            "financial_period_end": financials.get("financial_period_end"),
            "annual_periods_found": financials.get("annual_periods_found"),
            "financial_currency": financials.get("financial_currency"),
            "financial_taxonomy": financials.get("financial_taxonomy"),
            "pe_source": pe_source,
            "fmp_source_status": {
                key: endpoint_status.get(key)
                for key in (
                    "fmp_profile",
                    "fmp_quote",
                    "fmp_ratios_ttm",
                )
            },
            "scanner_version": "Scanner v4",
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
