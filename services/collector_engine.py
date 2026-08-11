from __future__ import annotations

from datetime import datetime, timezone


def number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def completeness(values):
    return round(
        sum(value is not None for value in values)
        / len(values) * 100,
        1,
    )


def scale(value, bad, good):
    if value is None:
        return 50.0
    return max(
        0,
        min(100, (value - bad) / (good - bad) * 100),
    )


def inverse(value, good, bad):
    if value is None:
        return 50.0
    return max(
        0,
        min(100, (bad - value) / (bad - good) * 100),
    )


class CollectorEngine:
    def __init__(
        self,
        fmp_client,
        sec_financial_client=None,
    ):
        self.fmp = fmp_client
        self.sec = sec_financial_client

    def safe(self, name, callback, empty):
        try:
            return callback(), "OK", None
        except Exception as exc:
            return empty, "ERİŞİLEMEDİ", f"{name}: {exc}"

    def collect(
        self,
        symbol,
        *,
        cik=None,
        participation_status="Kontrol Et",
        participation_score=60,
        portfolio_fit=55,
    ):
        errors = []
        endpoint_status = {}

        profile, endpoint_status["fmp_profile"], error = self.safe(
            "FMP profile",
            lambda: self.fmp.profile(symbol),
            {},
        )
        if error:
            errors.append(error)

        quote, endpoint_status["fmp_quote"], error = self.safe(
            "FMP quote",
            lambda: self.fmp.quote(symbol),
            {},
        )
        if error:
            errors.append(error)

        sec_values = {}
        if cik and self.sec:
            payload, endpoint_status["sec_companyfacts"], error = self.safe(
                "SEC Company Facts",
                lambda: self.sec.company_facts(cik),
                {},
            )
            if error:
                errors.append(error)
            elif payload:
                sec_values = self.sec.extract_financials(payload)
        else:
            endpoint_status["sec_companyfacts"] = "CIK YOK"

        price = number(
            quote.get("price")
            or profile.get("price")
        )
        market_cap = number(
            quote.get("marketCap")
            or profile.get("marketCap")
            or profile.get("mktCap")
        )

        revenue = sec_values.get("revenue")
        revenue_growth = sec_values.get("revenue_growth")
        eps_growth = sec_values.get("eps_growth")
        gross_margin = sec_values.get("gross_margin")
        operating_margin = sec_values.get("operating_margin")
        net_margin = sec_values.get("net_margin")
        free_cash_flow = sec_values.get("free_cash_flow")
        fcf_margin = sec_values.get("free_cash_flow_margin")
        roic = sec_values.get("roic")
        net_debt = sec_values.get("net_debt")
        current_ratio = sec_values.get("current_ratio")
        debt_to_equity = sec_values.get("debt_to_equity")

        pe = number(quote.get("pe"))
        peg = None

        data_completeness = completeness([
            price,
            market_cap,
            revenue,
            revenue_growth,
            eps_growth,
            operating_margin,
            net_margin,
            fcf_margin,
            roic,
            current_ratio,
            debt_to_equity,
            pe,
        ])

        quality = (
            scale(roic, 5, 30) * 0.35
            + scale(operating_margin, 5, 35) * 0.25
            + scale(net_margin, 3, 25) * 0.15
            + scale(gross_margin, 15, 70) * 0.10
            + scale(fcf_margin, 2, 25) * 0.15
        )
        growth_score = (
            scale(revenue_growth, 0, 25) * 0.45
            + scale(eps_growth, 0, 30) * 0.55
        )
        valuation = (
            inverse(pe, 12, 45) * 0.70
            + inverse(peg, 0.8, 3.0) * 0.30
        )
        financial_health = (
            scale(current_ratio, 0.8, 2.5) * 0.35
            + inverse(debt_to_equity, 0.2, 2.5) * 0.65
        )

        penalty = (
            1.0 if data_completeness >= 80
            else 0.9 if data_completeness >= 65
            else 0.78 if data_completeness >= 50
            else 0.60
        )

        raw_score = (
            quality * 0.24
            + growth_score * 0.18
            + valuation * 0.16
            + financial_health * 0.16
            + portfolio_fit * 0.14
            + 70 * 0.04
            + participation_score * 0.08
        )
        nabi_score = round(
            max(0, min(100, raw_score * penalty)),
            1,
        )

        if participation_status == "Uygun Değil":
            decision = "ELE"
            nabi_score = 0
        elif data_completeness < 50:
            decision = "VERİ EKSİK"
        elif nabi_score >= 82:
            decision = "GÜÇLÜ ADAY"
        elif nabi_score >= 68:
            decision = "İZLE"
        else:
            decision = "UZAK DUR"

        candidate = {
            "symbol": symbol,
            "company_name": (
                profile.get("companyName")
                or quote.get("name")
                or symbol
            ),
            "asset_type": (
                "ETF" if profile.get("isEtf") else "Hisse"
            ),
            "market": "ABD",
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
            "current_price": price,
            "market_cap": market_cap,
            "revenue": revenue,
            "revenue_growth": revenue_growth,
            "eps_growth": eps_growth,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "free_cash_flow": free_cash_flow,
            "free_cash_flow_margin": fcf_margin,
            "roic": roic,
            "net_debt": net_debt,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "pe_ratio": pe,
            "peg_ratio": peg,
            "quality_score": round(quality, 1),
            "growth_score": round(growth_score, 1),
            "valuation_score": round(valuation, 1),
            "financial_health_score": round(
                financial_health,
                1,
            ),
            "portfolio_fit_score": portfolio_fit,
            "liquidity_score": 70,
            "nabi_score": nabi_score,
            "decision": decision,
            "data_completeness": data_completeness,
            "data_source": "SEC + FMP",
            "source_updated_at": (
                datetime.now(timezone.utc).isoformat()
            ),
            "collector_notes": (
                " | ".join(errors)
                if errors else None
            ),
            "source_url": profile.get("website"),
            "notes": profile.get("description"),
            "cik": cik,
            "financial_period_end": sec_values.get(
                "financial_period_end"
            ),
        }

        return {
            "symbol": symbol,
            "candidate": candidate,
            "endpoint_status": endpoint_status,
            "errors": errors,
            "status": (
                "OK"
                if data_completeness >= 60
                else "KISMİ VERİ"
            ),
        }
