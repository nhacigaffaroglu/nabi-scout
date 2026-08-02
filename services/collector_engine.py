from datetime import datetime, timezone
from services.fmp_client import FMPError

def n(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None

def pct(value):
    value = n(value)
    if value is not None and abs(value) <= 2:
        value *= 100
    return value

def completeness(values):
    return round(sum(v is not None for v in values) / len(values) * 100, 1)

def scale(value, bad, good):
    if value is None:
        return 50.0
    return max(0, min(100, (value - bad) / (good - bad) * 100))

def inverse(value, good, bad):
    if value is None:
        return 50.0
    return max(0, min(100, (bad - value) / (bad - good) * 100))

class CollectorEngine:
    def __init__(self, client):
        self.client = client

    def safe(self, name, callback):
        try:
            return callback(), "OK", None
        except Exception as exc:
            return {}, "ERİŞİLEMEDİ", f"{name}: {exc}"

    def collect(self, symbol, participation_status="Kontrol Et",
                participation_score=60, portfolio_fit=55):
        errors, endpoint_status = [], {}

        profile, endpoint_status["profile"], err = self.safe(
            "profile", lambda: self.client.profile(symbol))
        if err: errors.append(err)

        quote, endpoint_status["quote"], err = self.safe(
            "quote", lambda: self.client.quote(symbol))
        if err: errors.append(err)

        income, endpoint_status["income"], err = self.safe(
            "income", lambda: self.client.income_statement(symbol))
        if err: errors.append(err)

        balance, endpoint_status["balance"], err = self.safe(
            "balance", lambda: self.client.balance_sheet(symbol))
        if err: errors.append(err)

        cashflow, endpoint_status["cashflow"], err = self.safe(
            "cashflow", lambda: self.client.cash_flow(symbol))
        if err: errors.append(err)

        ratios, endpoint_status["ratios"], err = self.safe(
            "ratios", lambda: self.client.ratios_ttm(symbol))
        if err: errors.append(err)

        metrics, endpoint_status["metrics"], err = self.safe(
            "metrics", lambda: self.client.key_metrics_ttm(symbol))
        if err: errors.append(err)

        growth, endpoint_status["growth"], err = self.safe(
            "growth", lambda: self.client.income_growth(symbol))
        if err: errors.append(err)

        inc = income[0] if isinstance(income, list) and income else {}
        bal = balance[0] if isinstance(balance, list) and balance else {}
        cf = cashflow[0] if isinstance(cashflow, list) and cashflow else {}

        price = n(quote.get("price") or profile.get("price"))
        market_cap = n(quote.get("marketCap") or profile.get("marketCap") or profile.get("mktCap"))
        revenue = n(inc.get("revenue"))
        op_income = n(inc.get("operatingIncome"))
        net_income = n(inc.get("netIncome"))
        gross_profit = n(inc.get("grossProfit"))
        ebitda = n(inc.get("ebitda"))
        free_cash_flow = n(cf.get("freeCashFlow"))
        debt = n(bal.get("totalDebt"))
        cash = n(bal.get("cashAndCashEquivalents") or bal.get("cashAndShortTermInvestments"))

        operating_margin = op_income / revenue * 100 if revenue and op_income is not None else None
        net_margin = net_income / revenue * 100 if revenue and net_income is not None else None
        gross_margin = gross_profit / revenue * 100 if revenue and gross_profit is not None else None
        fcf_margin = free_cash_flow / revenue * 100 if revenue and free_cash_flow is not None else None
        net_debt = debt - cash if debt is not None and cash is not None else None
        net_debt_ebitda = net_debt / ebitda if net_debt is not None and ebitda else None

        roic = pct(metrics.get("roicTTM") or metrics.get("returnOnInvestedCapitalTTM"))
        pe = n(quote.get("pe") or ratios.get("priceToEarningsRatioTTM") or ratios.get("peRatioTTM"))
        peg = n(ratios.get("priceEarningsToGrowthRatioTTM") or ratios.get("pegRatioTTM"))
        current_ratio = n(ratios.get("currentRatioTTM"))
        debt_to_equity = n(ratios.get("debtEquityRatioTTM") or ratios.get("debtToEquityRatioTTM"))
        revenue_growth = pct(growth.get("growthRevenue") or growth.get("revenueGrowth"))
        eps_growth = pct(growth.get("growthEPS") or growth.get("epsGrowth"))

        data_completeness = completeness([
            price, market_cap, revenue, operating_margin, net_margin,
            fcf_margin, roic, net_debt_ebitda, pe, peg,
            revenue_growth, eps_growth,
        ])

        quality = (
            scale(roic, 5, 30) * .35 +
            scale(operating_margin, 5, 35) * .25 +
            scale(net_margin, 3, 25) * .15 +
            scale(gross_margin, 15, 70) * .10 +
            scale(fcf_margin, 2, 25) * .15
        )
        growth_score = scale(revenue_growth, 0, 25) * .45 + scale(eps_growth, 0, 30) * .55
        valuation = inverse(pe, 12, 45) * .55 + inverse(peg, .8, 3) * .45
        health = (
            inverse(net_debt_ebitda, 0, 4) * .45 +
            scale(current_ratio, .8, 2.5) * .25 +
            inverse(debt_to_equity, .2, 2.5) * .30
        )
        penalty = 1 if data_completeness >= 80 else .9 if data_completeness >= 65 else .78 if data_completeness >= 50 else .6
        raw = (
            quality * .24 + growth_score * .18 + valuation * .16 +
            health * .16 + portfolio_fit * .14 + 70 * .04 +
            participation_score * .08
        )
        nabi_score = round(max(0, min(100, raw * penalty)), 1)

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
            "company_name": profile.get("companyName") or quote.get("name") or symbol,
            "asset_type": "ETF" if profile.get("isEtf") else "Hisse",
            "market": "ABD",
            "currency": profile.get("currency") or quote.get("currency") or "USD",
            "country": profile.get("country"),
            "sector_theme": profile.get("sector") or profile.get("industry"),
            "participation_status": participation_status,
            "participation_score": participation_score,
            "research_status": "Otomatik tarandı",
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
            "net_debt_ebitda": net_debt_ebitda,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "pe_ratio": pe,
            "peg_ratio": peg,
            "quality_score": round(quality, 1),
            "growth_score": round(growth_score, 1),
            "valuation_score": round(valuation, 1),
            "financial_health_score": round(health, 1),
            "portfolio_fit_score": portfolio_fit,
            "liquidity_score": 70,
            "nabi_score": nabi_score,
            "decision": decision,
            "data_completeness": data_completeness,
            "data_source": "FMP",
            "source_updated_at": datetime.now(timezone.utc).isoformat(),
            "collector_notes": " | ".join(errors) if errors else None,
            "source_url": profile.get("website"),
            "notes": profile.get("description"),
        }
        return {
            "symbol": symbol,
            "candidate": candidate,
            "endpoint_status": endpoint_status,
            "errors": errors,
            "status": "OK" if data_completeness >= 60 else "KISMİ VERİ",
        }
