"""Official TEFAS/KAP fund product provider. Intrinsic FI only. No 8E / New Money."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.fund_product_contract import (
    FUND_TYPE_MUTUAL,
    IDENTITY_RESOLVED,
    MANDATE_CONFIRMED,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    PILOT_TEFAS_FUND_CODES,
    PROFILE_EQUITY_PARTICIPATION_FUND,
    PROFILE_LIQUIDITY_PARTICIPATION_FUND,
    PROFILE_PARTICIPATION_EQUITY,
    PROFILE_PRECIOUS_METALS_PARTICIPATION,
    PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND,
    PROFILE_REAL_ESTATE_PARTICIPATION,
    PROFILE_REAL_ESTATE_PARTICIPATION_FUND,
    PROFILE_MIXED_MULTI_ASSET_PARTICIPATION,
    PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND,
    PROFILE_SHORT_TERM_PARTICIPATION,
    PROFILE_SUKUK_LEASE_CERTIFICATE,
    PROFILE_SUKUK_PARTICIPATION_FUND,
    PROVIDER_KAP_FUND,
    REGION_TR,
    PROVIDER_TEFAS,
    PURIFICATION_NOT_REQUIRED,
    READINESS_NEEDS_MORE_DATA,
    READINESS_READY_NOW,
    TEFAS_ENDPOINT_PRICES,
    TEFAS_ENDPOINT_RETURNS,
    TEFAS_ENDPOINT_SNAPSHOT,
    FundFacts,
    FundIdentity,
    FundPurificationEvidence,
    FundShariaEvidence,
    KapFundMandateEvidence,
    KapPortfolioReportAudit,
    OfficialFundEconomicClassification,
    OfficialFundMandate,
    OfficialFundPerformance,
    TefasPriceSeries,
    TurkiyeFundIdentity,
)
from services.official_kap_fund import (
    KAP_HOST,
    OZET_LABEL_FOUNDER,
    OZET_LABEL_UMBRELLA_TYPE,
    match_tefas_kap_identity,
    parse_kap_mandate,
    parse_kap_ozet_html,
    parse_kap_portfolio_report_audit,
)
from services.official_tefas import (
    TEFAS_HOST,
    normalize_fund_code,
    parse_tefas_price_history,
    parse_tefas_returns,
    parse_tefas_snapshot,
)
from services.official_kap_pdr import pdr_rows_to_official_holdings
from services.official_kap_pdr_evidence import try_load_captured_pdr_holdings
from services.official_tefas_performance import performance_from_tefas_series
from services.official_turkiye_fund_evidence import (
    load_kap_official_bundle,
    load_tefas_official_bundle,
    load_tefas_price_rows,
)
from services.official_turkiye_fund_participation import evaluate_turkiye_fund_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.security_master_contract import INSTRUMENT_OTHER, RESOLUTION_RESOLVED

TEFAS_SNAPSHOT_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_SNAPSHOT}"
TEFAS_RETURNS_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_RETURNS}"
TEFAS_PRICE_URL = f"{TEFAS_HOST}{TEFAS_ENDPOINT_PRICES}"


def _kap_fund(
    code: str,
    bundle: Mapping[str, Any],
    packs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    funds = dict(bundle.get("funds") or {})
    if code in funds:
        return dict(funds.get(code) or {})
    return dict((packs or {}).get(code) or {})


class TefasFundProductProvider:
    """Canonical TEFAS/KAP official-facts provider for intrinsic Fund Intelligence."""

    provider_id = PROVIDER_TEFAS

    def __init__(
        self,
        *,
        tefas_bundle: Optional[Mapping[str, Any]] = None,
        kap_bundle: Optional[Mapping[str, Any]] = None,
        price_rows: Optional[Mapping[str, Mapping[int, list[dict[str, Any]]]]] = None,
        evidence_packs: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> None:
        self._tefas = dict(tefas_bundle or load_tefas_official_bundle())
        self._kap = dict(kap_bundle or load_kap_official_bundle())
        self._price_rows = dict(price_rows or {})
        self._packs = {
            normalize_fund_code(code): dict(row)
            for code, row in dict(evidence_packs or {}).items()
        }

    def _snapshot_row(self, code: str) -> dict[str, Any]:
        snap = dict((self._tefas.get("snapshot") or {}).get(code) or {})
        if snap:
            return snap
        return dict((self._packs.get(code) or {}).get("tefas_snapshot") or {})

    def _returns_row(self, code: str) -> dict[str, Any]:
        row = dict((self._tefas.get("returns") or {}).get(code) or {})
        if row:
            return row
        return dict((self._packs.get(code) or {}).get("tefas_returns") or {})

    def supports(self, symbol: str) -> bool:
        code = normalize_fund_code(symbol)
        if code in dict(self._kap.get("funds") or {}) and code in dict(self._tefas.get("snapshot") or {}):
            return True
        pack = dict(self._packs.get(code) or {})
        if not pack:
            return False
        snap = dict(self._tefas.get("snapshot") or {}).get(code) or pack.get("tefas_snapshot")
        identity_ok = pack.get("identity_status") == IDENTITY_RESOLVED
        return bool(identity_ok and snap)

    def _require(self, symbol: str) -> str:
        code = normalize_fund_code(symbol)
        if not self.supports(code):
            raise ValueError(f"unsupported_tefas_fund:{code or symbol}")
        return code

    def turkiye_identity(self, symbol: str) -> TurkiyeFundIdentity:
        code = self._require(symbol)
        snap = parse_tefas_snapshot(self._snapshot_row(code))
        returns = parse_tefas_returns(self._returns_row(code))
        kap = _kap_fund(code, self._kap, self._packs)
        ozet = dict(kap.get("ozet_fields") or {})
        ybf = dict(kap.get("ybf") or {})
        status = match_tefas_kap_identity(tefas_code=snap.get("fonKodu") or code, kap_code=kap.get("fund_code"))
        currency = "TRY" if "TL" in str(ybf.get("currency_sentence") or "") else None
        return TurkiyeFundIdentity(
            fund_code=code,
            official_name=str(snap.get("fonUnvan") or ybf.get("official_name") or "") or None,
            fund_type=str(returns.get("fonTurAciklama") or ozet.get(OZET_LABEL_UMBRELLA_TYPE) or "") or None,
            currency=currency,
            founder=ozet.get(OZET_LABEL_FOUNDER),
            portfolio_manager=str(ybf.get("portfolio_manager") or "") or None,
            tefas_source=PROVIDER_TEFAS,
            tefas_source_url=TEFAS_SNAPSHOT_URL,
            kap_source=PROVIDER_KAP_FUND,
            kap_source_url=str(kap.get("ozet_url") or ""),
            identity_status=status,
            as_of=None,
            isin=str(ybf.get("isin") or "") or None,
            umbrella_type=ozet.get(OZET_LABEL_UMBRELLA_TYPE),
            limitations=() if status == IDENTITY_RESOLVED else ("IDENTITY_UNRESOLVED",),
        )

    def identity(self, symbol: str) -> FundIdentity:
        row = self.turkiye_identity(symbol)
        return FundIdentity(
            symbol=row.fund_code,
            official_name=row.official_name,
            instrument_type=INSTRUMENT_OTHER,
            fund_type=FUND_TYPE_MUTUAL,
            issuer_family=row.founder,
            exchange=None,
            currency=row.currency,
            cusip=None,
            security_master_status=RESOLUTION_RESOLVED if row.identity_status == IDENTITY_RESOLVED else "UNKNOWN",
            source=PROVIDER_TEFAS,
            source_url=row.tefas_source_url,
            limitations=row.limitations,
        )

    def facts(self, symbol: str) -> FundFacts:
        code = self._require(symbol)
        snap = parse_tefas_snapshot(self._snapshot_row(code))
        returns = parse_tefas_returns(self._returns_row(code))
        mandate = self.kap_mandate(code)
        raw = {key: "" if value is None else str(value) for key, value in {**snap, **returns}.items()}
        nav = snap.get("sonFiyat")
        assets = snap.get("portBuyukluk")
        return FundFacts(
            symbol=code,
            official_name=str(snap.get("fonUnvan") or "") or None,
            fund_type=FUND_TYPE_MUTUAL,
            asset_class=str(snap.get("fonKategori") or "") or None,
            strategy=mandate.strategy_text,
            benchmark=mandate.benchmark,
            nav=float(nav) if nav is not None else None,
            market_price=None,
            net_assets=float(assets) if assets is not None else None,
            expense_ratio=mandate.management_fee_annual_pct,
            inception_date=None,
            latest_distribution=None,
            holdings_as_of=None,
            holdings_count=None,
            exchange=None,
            currency=mandate.currency_restriction,
            cusip=None,
            sharia_methodology=None,
            source=PROVIDER_TEFAS,
            source_url=TEFAS_SNAPSHOT_URL,
            as_of=None,
            limitations=("NO_EIGHT_E", "NO_NEW_MONEY", "KAP_MANAGEMENT_FEE_NOT_TER"),
            raw_fields=raw,
        )

    def kap_mandate(self, symbol: str) -> KapFundMandateEvidence:
        code = self._require(symbol)
        kap = _kap_fund(code, self._kap, self._packs)
        return parse_kap_mandate(
            fund_code=code,
            ozet_fields=dict(kap.get("ozet_fields") or {}),
            ybf_text=str(kap.get("ybf_text") or ""),
            ybf_payload=dict(kap.get("ybf") or {}),
            source_url=str(kap.get("ozet_url") or ""),
            ybf_url=str(kap.get("ybf_url") or ""),
            as_of=str((kap.get("ybf") or {}).get("as_of") or "") or None,
        )

    def mandate(self, symbol: str) -> OfficialFundMandate:
        return mandate_from_kap(self.kap_mandate(symbol))

    def economic_classification(self, symbol: str) -> Optional[OfficialFundEconomicClassification]:
        from services.official_turkiye_fund_exposure import classify_official_turkiye_fund_exposure

        code = self._require(symbol)
        return classify_official_turkiye_fund_exposure(self.mandate(code), self.pdr_holdings(code))

    def performance(self, symbol: str) -> OfficialFundPerformance:
        code = self._require(symbol)
        return performance_from_tefas_series(
            self.price_history(code, period_months=12),
            official_risk_value=self.official_risk_value(code),
        )

    def holdings(self, symbol: str):
        file = self.pdr_holdings(symbol)
        if file is None:
            return None
        return pdr_rows_to_official_holdings(file)

    def sharia_evidence(self, symbol: str) -> FundShariaEvidence:
        code = self._require(symbol)
        mandate = self.kap_mandate(code)
        identity = self.turkiye_identity(code)
        verdict = evaluate_turkiye_fund_participation(
            code,
            identity_status=identity.identity_status,
            official_name=identity.official_name,
            umbrella_type=mandate.umbrella_type,
            official_profile=mandate.official_profile,
        )
        uygun = verdict.participation_status == PARTICIPATION_STATUS_UYGUN
        limitations = ["NO_INVENTED_UYGUN"]
        if uygun:
            if verdict.equivalent_approval_reason:
                limitations.append("EQUIVALENT_ICAZET_MECHANISM")
        else:
            limitations.extend(verdict.blockers)
        excerpts = mandate.participation_wording + tuple(
            item.raw_text
            for item in verdict.evidence
            if item.evidence_type in {"MANDATE", "GOVERNANCE"} and item.fund_code == code
        )
        return FundShariaEvidence(
            symbol=code,
            official_mandate_present=verdict.mandate_state == MANDATE_CONFIRMED,
            official_certificate_listed=uygun,
            official_auditor_report_listed=False,
            methodology=METHODOLOGY_TURKIYE_FUND_PARTICIPATION if uygun else None,
            auditor=None,
            benchmark_sharia=False,
            source=PROVIDER_KAP_FUND,
            source_url=mandate.source_url,
            evidence_as_of=mandate.as_of,
            excerpts=tuple(dict.fromkeys(excerpts)),
            confidence="HIGH" if uygun else "LOW",
            eligibility_ready=READINESS_READY_NOW if uygun else READINESS_NEEDS_MORE_DATA,
            participation_status=verdict.participation_status,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def purification_evidence(self, symbol: str) -> FundPurificationEvidence:
        code = self._require(symbol)
        kap = _kap_fund(code, self._kap, self._packs)
        identity = self.turkiye_identity(code)
        kap_mandate = self.kap_mandate(code)
        verdict = evaluate_turkiye_fund_participation(
            code,
            identity_status=identity.identity_status,
            official_name=identity.official_name,
            umbrella_type=kap_mandate.umbrella_type,
            official_profile=kap_mandate.official_profile,
        )
        required = False if verdict.purification_state == PURIFICATION_NOT_REQUIRED else None
        return FundPurificationEvidence(
            symbol=code,
            purification_required=required,
            latest_factor_pct=None,
            factor_period=None,
            source=PROVIDER_KAP_FUND,
            source_url=str(kap.get("ybf_url") or kap.get("ozet_url") or ""),
            as_of=None,
            methodology=METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
            factors=(),
            limitations=("PURIFICATION_FACTOR_UNAVAILABLE",),
        )

    def price_history(self, symbol: str, *, period_months: int = 12) -> TefasPriceSeries:
        code = self._require(symbol)
        override = (self._price_rows.get(code) or {}).get(period_months)
        if override is not None:
            rows = list(override)
        else:
            try:
                rows = load_tefas_price_rows(code, period_months=period_months)
            except (FileNotFoundError, ValueError, OSError):
                rows = list((self._packs.get(code) or {}).get("tefas_price_rows") or [])
        return parse_tefas_price_history(
            rows,
            fund_code=code,
            period_months=period_months,
            source_url=TEFAS_PRICE_URL,
        )

    def portfolio_report_audit(self, symbol: str) -> KapPortfolioReportAudit:
        code = self._require(symbol)
        kap = _kap_fund(code, self._kap, self._packs)
        return parse_kap_portfolio_report_audit(fund_code=code, report=dict(kap.get("portfolio_report") or {}))

    def pdr_holdings(self, symbol: str):
        return try_load_captured_pdr_holdings(self._require(symbol))

    def official_risk_value(self, symbol: str) -> Optional[str]:
        code = self._require(symbol)
        returns = parse_tefas_returns(self._returns_row(code))
        value = returns.get("riskDegeri")
        return str(value).strip() if value is not None and str(value).strip() else None

    def investor_count(self, symbol: str) -> Optional[int]:
        code = self._require(symbol)
        snap = parse_tefas_snapshot(self._snapshot_row(code))
        raw = snap.get("yatirimciSayi")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def mandate_from_kap(kap: KapFundMandateEvidence) -> OfficialFundMandate:
    """Map official KAP profile facts onto the shared OfficialFundMandate."""
    profile = kap.official_profile
    if profile == PROFILE_SHORT_TERM_PARTICIPATION:
        layer, vehicle = "cash_like", PROFILE_LIQUIDITY_PARTICIPATION_FUND
    elif profile == PROFILE_PARTICIPATION_EQUITY:
        layer, vehicle = "equity", PROFILE_EQUITY_PARTICIPATION_FUND
    elif profile == PROFILE_SUKUK_LEASE_CERTIFICATE:
        layer, vehicle = "sukuk", PROFILE_SUKUK_PARTICIPATION_FUND
    elif profile == PROFILE_PRECIOUS_METALS_PARTICIPATION:
        layer, vehicle = "precious_metals", PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND
    elif profile in {PROFILE_REAL_ESTATE_PARTICIPATION, PROFILE_REAL_ESTATE_PARTICIPATION_FUND}:
        layer, vehicle = "real_estate", PROFILE_REAL_ESTATE_PARTICIPATION_FUND
    elif profile in {PROFILE_MIXED_MULTI_ASSET_PARTICIPATION, PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND}:
        layer, vehicle = "multi_asset", PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND
    else:
        raise ValueError(f"unsupported_kap_official_profile:{profile}")
    mandate = OfficialFundMandate(
        symbol=kap.fund_code,
        primary_layer=layer,
        region=REGION_TR,
        vehicle=vehicle,
        confidence="HIGH",
        source=kap.source,
        source_url=kap.source_url,
        evidence_excerpt=kap.strategy_text or kap.official_name or kap.fund_code,
        limitations=kap.limitations,
    )
    mandate.validate()
    return mandate


def try_mandate_from_kap(kap: KapFundMandateEvidence) -> Optional[OfficialFundMandate]:
    try:
        return mandate_from_kap(kap)
    except ValueError:
        return None


def default_tefas_fund_provider(
    *,
    evidence_packs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> TefasFundProductProvider:
    packs = evidence_packs
    if packs is None:
        from services.turkiye_fund_source_capture import load_cached_evidence_packs

        packs = load_cached_evidence_packs()
    official_codes = set(dict(load_tefas_official_bundle().get("snapshot") or {}))
    price_rows: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for code, pack in dict(packs or {}).items():
        if code in official_codes:
            continue
        rows = list(pack.get("tefas_price_rows") or [])
        if rows:
            price_rows[code] = {12: rows}
    return TefasFundProductProvider(evidence_packs=packs, price_rows=price_rows)


def supported_tefas_pilot_codes() -> tuple[str, ...]:
    return PILOT_TEFAS_FUND_CODES
