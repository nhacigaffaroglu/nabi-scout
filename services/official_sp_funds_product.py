"""Parse official SP Funds public product pages and purification tables.

Classification uses official mandate text, never ticker-name shortcuts.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

from services.official_fund_nport import parse_official_nport_xml
from services.official_fund_performance import (
    parse_official_performance_html,
    parse_official_sec_yield_html,
    select_market_performance,
    select_nav_performance,
)
from services.fund_product_contract import (
    DIM_CONCENTRATION,
    DIM_COST,
    DIM_COUNTRY_CURRENCY,
    DIM_DIVERSIFICATION,
    DIM_DURATION_YIELD,
    DIM_LIQUIDITY,
    DIM_PARTICIPATION,
    DIM_PERFORMANCE,
    DIM_PORTFOLIO_FIT,
    DIM_REAL_ESTATE_RISK,
    DIM_RISK,
    DIM_TRACKING,
    FUND_TYPE_ETF,
    PILOT_FUND_SYMBOLS,
    PROVIDER_SP_FUNDS_OFFICIAL,
    PROVIDER_TEFAS,
    READINESS_NEEDS_MORE_DATA,
    READINESS_NOT_APPLICABLE,
    READINESS_READY_NOW,
    REGION_GLOBAL,
    REGION_INTERNATIONAL_EX_US,
    REGION_US,
    DimensionReadiness,
    FundFacts,
    FundIdentity,
    FundIntelligenceReadiness,
    FundProductProvider,
    FundPurificationEvidence,
    FundShariaEvidence,
    OfficialFundMandate,
    OfficialFundPerformance,
    OfficialFundYield,
    OfficialNportSnapshot,
    PurificationFactor,
)
from services.security_identity_contract import ECONOMIC_LAYERS
from services.security_master_contract import INSTRUMENT_ETF, RESOLUTION_UNKNOWN

PRODUCT_URL_TEMPLATE = "https://www.sp-funds.com/{symbol}/"
PURIFICATION_URL = "https://www.sp-funds.com/purification-calculator/"
ISSUER_FAMILY = "SP Funds"
CURRENCY_USD = "USD"

_DETAIL_LABELS = {
    "fund inception": "inception_date",
    "ticker": "ticker",
    "primary exchange": "exchange",
    "cusip": "cusip",
    "expense ratio": "expense_ratio",
    "net assets": "net_assets",
    "nav": "nav",
    "closing price": "market_price",
    "shares outstanding": "shares_outstanding",
}


def official_product_url(symbol: str) -> str:
    return PRODUCT_URL_TEMPLATE.format(symbol=str(symbol or "").strip().lower())


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _first_heading_name(html: str) -> Optional[str]:
    match = re.search(
        r"(?:The\s+)?SP Funds[^<\n]{8,120}",
        html or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip(" #")


def _table_pairs(html: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for match in re.finditer(
        r"\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|",
        html or "",
    ):
        label = re.sub(r"\s+", " ", match.group(1)).strip().lower()
        label = label.rstrip("* ").strip()
        value = re.sub(r"\s+", " ", match.group(2)).strip()
        if label in {"name", "value"} or not value:
            continue
        key = _DETAIL_LABELS.get(label)
        if key and key not in pairs:
            pairs[key] = value
    return pairs


def _parse_pct(raw: str) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    text = re.sub(r"[*%].*$", "", text).strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_money(raw: str) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "").replace("$", "")
    multiplier = 1.0
    if text.lower().endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    elif text.lower().endswith("b"):
        multiplier = 1_000_000_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_official_product_html(
    html: str,
    *,
    symbol: str,
    source_url: str = "",
) -> FundFacts:
    fund = _norm_symbol(symbol)
    if fund not in PILOT_FUND_SYMBOLS:
        raise ValueError(f"unsupported official fund product: {symbol}")
    pairs = _table_pairs(html)
    limitations: list[str] = []
    table_ticker = str(pairs.get("ticker") or "").strip().upper()
    if table_ticker and table_ticker != fund:
        limitations.append("OFFICIAL_TABLE_TICKER_MISMATCH")
    official_name = _first_heading_name(html)
    methodology = None
    if re.search(r"AAOIFI", html or "", flags=re.IGNORECASE):
        methodology = "AAOIFI"
    benchmark = None
    bench = re.search(
        r"(S&P [^.\n]{8,80}Index|Dow Jones Sukuk[^.\n]{0,80}Index)",
        html or "",
        flags=re.IGNORECASE,
    )
    if bench:
        benchmark = re.sub(r"\s+", " ", bench.group(1)).strip()
    strategy = None
    if official_name:
        strategy = official_name
    latest_distribution = None
    dist = re.search(
        r"\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*\d{2}/\d{2}/\d{4}\s*\|\s*\d{2}/\d{2}/\d{4}\s*\|\s*([0-9.]+)\s*\|",
        html or "",
    )
    if dist:
        latest_distribution = f"{dist.group(1)} {dist.group(2)}"
    return FundFacts(
        symbol=fund,
        official_name=official_name,
        fund_type=FUND_TYPE_ETF,
        asset_class=None,
        strategy=strategy,
        benchmark=benchmark,
        nav=_parse_money(pairs.get("nav") or ""),
        market_price=_parse_money(pairs.get("market_price") or ""),
        net_assets=_parse_money(pairs.get("net_assets") or ""),
        expense_ratio=_parse_pct(pairs.get("expense_ratio") or ""),
        inception_date=pairs.get("inception_date"),
        latest_distribution=latest_distribution,
        exchange=pairs.get("exchange"),
        currency=CURRENCY_USD,
        cusip=pairs.get("cusip"),
        sharia_methodology=methodology,
        source=PROVIDER_SP_FUNDS_OFFICIAL,
        source_url=source_url or official_product_url(fund),
        as_of=None,
        limitations=tuple(limitations),
        raw_fields=pairs,
    )


def identity_from_facts(
    facts: FundFacts,
    *,
    security_master_status: str = RESOLUTION_UNKNOWN,
) -> FundIdentity:
    return FundIdentity(
        symbol=facts.symbol,
        official_name=facts.official_name,
        instrument_type=INSTRUMENT_ETF,
        fund_type=facts.fund_type,
        issuer_family=ISSUER_FAMILY,
        exchange=facts.exchange,
        currency=facts.currency,
        cusip=facts.cusip,
        security_master_status=security_master_status,
        source=facts.source,
        source_url=facts.source_url,
        limitations=facts.limitations,
    )


def mandate_from_official_facts(facts: FundFacts) -> OfficialFundMandate:
    """Derive economic layer from official name/benchmark/strategy text only."""
    blob = " ".join(
        part
        for part in (facts.official_name, facts.benchmark, facts.strategy)
        if part
    ).lower()
    limitations: list[str] = []
    vehicle = None
    region = REGION_US
    primary = ""
    excerpt = facts.official_name or facts.benchmark or ""
    if "sukuk" in blob:
        primary = "sukuk"
        vehicle = "SUKUK"
        region = REGION_GLOBAL
    elif "reit" in blob or "real estate" in blob:
        primary = "real_estate"
        vehicle = "REIT"
        region = REGION_GLOBAL
    elif "world" in blob and ("ex-us" in blob or "ex-u.s" in blob or "ex us" in blob):
        primary = "equity"
        region = REGION_INTERNATIONAL_EX_US
    elif "s&p 500" in blob or "sharia industry exclusions" in blob:
        primary = "equity"
        region = REGION_US
    if primary not in ECONOMIC_LAYERS:
        raise ValueError("official mandate text does not identify a canonical economic layer")
    if not excerpt:
        limitations.append("MANDATE_EXCERPT_THIN")
    mandate = OfficialFundMandate(
        symbol=facts.symbol,
        primary_layer=primary,
        region=region,
        vehicle=vehicle,
        confidence="HIGH",
        source=facts.source,
        source_url=facts.source_url,
        evidence_excerpt=excerpt,
        limitations=tuple(limitations),
    )
    mandate.validate()
    return mandate


def parse_sharia_evidence_html(
    html: str,
    *,
    symbol: str,
    source_url: str = "",
) -> FundShariaEvidence:
    fund = _norm_symbol(symbol)
    text = html or ""
    excerpts: list[str] = []
    mandate = bool(
        re.search(
            r"Sharia[h]?-compliant|Islamic ethical principles|Islamic finance principles",
            text,
            re.I,
        )
    )
    certificate = bool(re.search(r"Certificate of Sharia Accreditation", text, re.I))
    auditor = bool(re.search(r"Sharia Auditor Report", text, re.I))
    methodology = "AAOIFI" if re.search(r"AAOIFI", text, re.I) else None
    if mandate:
        excerpts.append("official Sharia-compliant mandate language present")
    if certificate:
        excerpts.append("Certificate of Sharia Accreditation listed")
    if auditor:
        excerpts.append("Sharia Auditor Report listed")
    if methodology:
        excerpts.append("AAOIFI methodology cited")
    if certificate and mandate and methodology:
        ready = READINESS_READY_NOW
        confidence = "HIGH"
    elif mandate and methodology:
        ready = READINESS_NEEDS_MORE_DATA
        confidence = "MEDIUM"
    else:
        ready = READINESS_NEEDS_MORE_DATA
        confidence = "LOW"
    return FundShariaEvidence(
        symbol=fund,
        official_mandate_present=mandate,
        official_certificate_listed=certificate,
        official_auditor_report_listed=auditor,
        methodology=methodology,
        auditor="ShariaPortfolio" if auditor or methodology else None,
        benchmark_sharia=bool(re.search(r"Sharia[h]?", text, re.I)),
        source=PROVIDER_SP_FUNDS_OFFICIAL,
        source_url=source_url or official_product_url(fund),
        evidence_as_of=None,
        excerpts=tuple(excerpts),
        confidence=confidence,
        eligibility_ready=ready,
        participation_status=None,
        limitations=("NO_INVENTED_UYGUN",),
    )


def parse_purification_html(html: str, *, source_url: str = PURIFICATION_URL) -> dict[str, FundPurificationEvidence]:
    text = html or ""
    exempt_symbols = {
        token.upper()
        for token in re.findall(
            r"\b([A-Z]{3,5})\s+does not require purification",
            text,
            flags=re.I,
        )
    }
    methodology = None
    if re.search(r"AAOIFI", text, re.I):
        methodology = "ShariaPortfolio / AAOIFI"
    header: list[str] = []
    header_match = re.search(r"\|\s*Date\s*\|\s*(.+?)\|", text)
    if header_match:
        header = [part.strip().upper() for part in header_match.group(1).split("|") if part.strip()]
    factors: dict[str, list[PurificationFactor]] = {symbol: [] for symbol in PILOT_FUND_SYMBOLS}
    for row in re.finditer(
        r"\|\s*(Q[1-4]\s+\d{4})\s*\|\s*([^|\n]*)\s*\|\s*([^|\n]*)\s*\|\s*([^|\n]*)\s*\|\s*([^|\n]*)\s*\|",
        text,
    ):
        period = row.group(1).strip()
        values = [row.group(i).strip() for i in range(2, 6)]
        mapped = header[:4] if len(header) >= 4 else ("SPUS", "SPRE", "SPTE", "SPWO")
        for symbol, raw in zip(mapped, values):
            if symbol not in factors:
                continue
            factor = _parse_pct(raw) if raw else None
            if factor is None and not raw:
                continue
            factors[symbol].append(
                PurificationFactor(
                    symbol=symbol,
                    period=period,
                    factor_pct=factor,
                    source=PROVIDER_SP_FUNDS_OFFICIAL,
                    source_url=source_url,
                )
            )
    out: dict[str, FundPurificationEvidence] = {}
    for symbol in PILOT_FUND_SYMBOLS:
        if symbol in exempt_symbols:
            out[symbol] = FundPurificationEvidence(
                symbol=symbol,
                purification_required=False,
                latest_factor_pct=None,
                factor_period=None,
                source=PROVIDER_SP_FUNDS_OFFICIAL,
                source_url=source_url,
                as_of=None,
                methodology=methodology,
                factors=(),
                limitations=(),
            )
            continue
        series = tuple(factors.get(symbol) or ())
        latest = series[0] if series else None
        out[symbol] = FundPurificationEvidence(
            symbol=symbol,
            purification_required=True if series else None,
            latest_factor_pct=latest.factor_pct if latest else None,
            factor_period=latest.period if latest else None,
            source=PROVIDER_SP_FUNDS_OFFICIAL,
            source_url=source_url,
            as_of=latest.period if latest else None,
            methodology=methodology,
            factors=series,
            limitations=() if series else ("PURIFICATION_FACTOR_UNAVAILABLE",),
        )
    return out


def fund_intelligence_readiness(
    *,
    facts: FundFacts,
    mandate: Optional[OfficialFundMandate],
    sharia: Optional[FundShariaEvidence],
    purification: Optional[FundPurificationEvidence],
    lookthrough_unknown_pct: Optional[float],
    official_performance_present: bool,
) -> FundIntelligenceReadiness:
    primary = mandate.primary_layer if mandate else ""

    def _dim(name: str, state: str, note: str = "") -> DimensionReadiness:
        return DimensionReadiness(dimension=name, state=state, note=note)

    dims = [
        _dim(
            DIM_PARTICIPATION,
            sharia.eligibility_ready if sharia else READINESS_NEEDS_MORE_DATA,
            "official Sharia governance evidence; Uygun not invented",
        ),
        _dim(
            DIM_PERFORMANCE,
            READINESS_READY_NOW if official_performance_present else READINESS_NEEDS_MORE_DATA,
            "official NAV/market performance periods only",
        ),
        _dim(DIM_RISK, READINESS_NEEDS_MORE_DATA, "official drawdown series not captured this sprint"),
        _dim(
            DIM_COST,
            READINESS_READY_NOW if facts.expense_ratio is not None else READINESS_NEEDS_MORE_DATA,
        ),
        _dim(
            DIM_DIVERSIFICATION,
            READINESS_NEEDS_MORE_DATA if lookthrough_unknown_pct is None else READINESS_READY_NOW,
            "holdings-weighted concentration only; no guessed sectors",
        ),
        _dim(
            DIM_CONCENTRATION,
            READINESS_READY_NOW if lookthrough_unknown_pct is not None else READINESS_NEEDS_MORE_DATA,
        ),
        _dim(DIM_TRACKING, READINESS_NEEDS_MORE_DATA, "tracking error not computed from official NAV yet"),
        _dim(
            DIM_LIQUIDITY,
            READINESS_READY_NOW if facts.market_price is not None else READINESS_NEEDS_MORE_DATA,
        ),
        _dim(DIM_PORTFOLIO_FIT, READINESS_NEEDS_MORE_DATA, "requires live portfolio context"),
        _dim(
            DIM_DURATION_YIELD,
            READINESS_NOT_APPLICABLE if primary != "sukuk" else READINESS_NEEDS_MORE_DATA,
            "sukuk duration/credit needs official holdings metadata",
        ),
        _dim(
            DIM_REAL_ESTATE_RISK,
            READINESS_NOT_APPLICABLE if primary != "real_estate" else READINESS_NEEDS_MORE_DATA,
        ),
        _dim(
            DIM_COUNTRY_CURRENCY,
            READINESS_NOT_APPLICABLE
            if mandate is None or mandate.region == REGION_US
            else READINESS_NEEDS_MORE_DATA,
            "country/currency stay UNKNOWN without official classification",
        ),
    ]
    _ = purification
    return FundIntelligenceReadiness(symbol=facts.symbol, dimensions=tuple(dims), invented_score=False)


class OfficialSpFundsProductProvider:
    provider_id = PROVIDER_SP_FUNDS_OFFICIAL

    def __init__(
        self,
        *,
        product_html: dict[str, str],
        purification_html: str = "",
        nport_xml: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._product_html = {key.upper(): value for key, value in product_html.items()}
        self._purification = parse_purification_html(purification_html) if purification_html else {}
        self._nport_xml = {key.upper(): value for key, value in (nport_xml or {}).items()}

    def supports(self, symbol: str) -> bool:
        return _norm_symbol(symbol) in PILOT_FUND_SYMBOLS

    def facts(self, symbol: str) -> FundFacts:
        fund = _norm_symbol(symbol)
        html = self._product_html.get(fund)
        if not html:
            raise ValueError(f"official product html missing for {fund}")
        return parse_official_product_html(html, symbol=fund)

    def identity(self, symbol: str) -> FundIdentity:
        return identity_from_facts(self.facts(symbol))

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence:
        fund = _norm_symbol(symbol)
        html = self._product_html.get(fund) or ""
        return parse_sharia_evidence_html(html, symbol=fund)

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence:
        fund = _norm_symbol(symbol)
        if fund in self._purification:
            return self._purification[fund]
        raise ValueError(f"official purification html missing for {fund}")

    def mandate(self, symbol: str) -> OfficialFundMandate:
        return mandate_from_official_facts(self.facts(symbol))

    def performance_rows(self, symbol: str) -> dict[str, OfficialFundPerformance]:
        fund = _norm_symbol(symbol)
        html = self._product_html.get(fund)
        if not html:
            raise ValueError(f"official product html missing for {fund}")
        return parse_official_performance_html(html, symbol=fund)

    def performance(self, symbol: str) -> Optional[OfficialFundPerformance]:
        return select_nav_performance(self.performance_rows(symbol))

    def market_performance(self, symbol: str) -> Optional[OfficialFundPerformance]:
        return select_market_performance(self.performance_rows(symbol))

    def sec_yield(self, symbol: str) -> Optional[OfficialFundYield]:
        fund = _norm_symbol(symbol)
        html = self._product_html.get(fund) or ""
        return parse_official_sec_yield_html(html, symbol=fund)

    def nport_snapshot(self, symbol: str) -> Optional[OfficialNportSnapshot]:
        fund = _norm_symbol(symbol)
        xml_text = self._nport_xml.get(fund)
        if not xml_text:
            return None
        return parse_official_nport_xml(xml_text, symbol=fund)


class TefasFundProductProvider:
    """Architecture stub. Same contract, no SP-Funds-only engine."""

    provider_id = PROVIDER_TEFAS

    def supports(self, symbol: str) -> bool:
        _ = symbol
        return False

    def identity(self, symbol: str) -> FundIdentity:
        raise NotImplementedError("TEFAS identity is not implemented this sprint")

    def facts(self, symbol: str) -> FundFacts:
        raise NotImplementedError("TEFAS facts are not implemented this sprint")

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence:
        raise NotImplementedError("TEFAS sharia evidence is not implemented this sprint")

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence:
        raise NotImplementedError("TEFAS purification is not implemented this sprint")


def assert_provider_surface(provider: FundProductProvider) -> tuple[str, ...]:
    return ("supports", "identity", "facts", "sharia_evidence", "purification_evidence")


def default_official_sp_funds_provider() -> OfficialSpFundsProductProvider:
    from services.official_fund_nport_evidence import NPORT_XML
    from services.official_sp_funds_evidence import PRODUCT_HTML, PURIFICATION_HTML

    return OfficialSpFundsProductProvider(
        product_html=PRODUCT_HTML,
        purification_html=PURIFICATION_HTML,
        nport_xml=NPORT_XML,
    )


def validate_canonical_mandate(mandate: Any) -> Optional[OfficialFundMandate]:
    """Accept only a validated OfficialFundMandate. Strings and invalid layers fail closed."""
    if not isinstance(mandate, OfficialFundMandate):
        return None
    try:
        mandate.validate()
    except ValueError:
        return None
    if mandate.primary_layer not in ECONOMIC_LAYERS:
        return None
    return mandate


def resolve_official_fund_mandates(
    symbols: Sequence[str],
    *,
    explicit: Optional[Mapping[str, Any]] = None,
    provider: Optional[Any] = None,
) -> dict[str, OfficialFundMandate]:
    """Resolve official mandates. Precedence: valid explicit → canonical → omit (unknown).

    Invalid explicit overrides fail closed and do not fall through.
    Provider/source failure and unsupported symbols are omitted.
    """
    resolved_provider = provider
    if resolved_provider is None:
        try:
            resolved_provider = default_official_sp_funds_provider()
        except Exception:
            resolved_provider = None
    out: dict[str, OfficialFundMandate] = {}
    for raw in symbols:
        symbol = _norm_symbol(raw)
        if not symbol:
            continue
        if explicit is not None and symbol in explicit:
            validated = validate_canonical_mandate(explicit[symbol])
            if validated is not None:
                out[symbol] = validated
            continue
        if resolved_provider is None:
            continue
        try:
            if not resolved_provider.supports(symbol):
                continue
            validated = validate_canonical_mandate(resolved_provider.mandate(symbol))
        except Exception:
            continue
        if validated is not None:
            out[symbol] = validated
    return out
