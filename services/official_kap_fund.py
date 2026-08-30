"""Parse official KAP fund identity and mandate evidence.

Identity matching uses official fund code only. Names are never a match key.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from services.fund_product_contract import (
    IDENTITY_RESOLVED,
    IDENTITY_UNRESOLVED,
    KapFundMandateEvidence,
    KapPortfolioReportAudit,
    PDR_FIELD_ASSET_WEIGHTS,
    PDR_FIELD_CURRENCY,
    PDR_FIELD_HOLDINGS,
    PDR_FIELD_ISIN,
    PDR_FIELD_ISSUER,
    PDR_FIELD_MATURITY,
    PROFILE_PARTICIPATION_EQUITY,
    PROFILE_SHORT_TERM_PARTICIPATION,
    PROFILE_SUKUK_LEASE_CERTIFICATE,
    PROVIDER_KAP_FUND,
)
from services.official_tefas import normalize_fund_code

KAP_HOST = "https://www.kap.org.tr"

OZET_LABEL_FOUNDER = "Kurucunun Ünvanı"
OZET_LABEL_UMBRELLA_NAME = "Fonun Bağlı Olduğu Şemsiye Fonun Ünvanı"
OZET_LABEL_UMBRELLA_TYPE = "Fonun Bağlı Olduğu Şemsiye Fonun Türü"

_H3_PAIR = re.compile(
    r"<h3[^>]*>(.*?)</h3>\s*<[^>]+>(.*?)</",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")


def match_tefas_kap_identity(
    *,
    tefas_code: Any,
    kap_code: Any,
    tefas_name: Any = None,
    kap_name: Any = None,
) -> str:
    """Deterministic code match only. Names are ignored even when identical."""
    _ = tefas_name, kap_name
    left = normalize_fund_code(tefas_code)
    right = normalize_fund_code(kap_code)
    if left and right and left == right:
        return IDENTITY_RESOLVED
    return IDENTITY_UNRESOLVED


def _plain(raw: Any) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", str(raw or ""))).strip()


def parse_kap_ozet_html(html: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for label_html, value_html in _H3_PAIR.findall(html or ""):
        label = _plain(label_html)
        value = _plain(value_html)
        if label and value and label not in pairs:
            pairs[label] = value
    return pairs


def parse_kap_ybf_text(text: str) -> dict[str, Any]:
    body = str(text or "")
    isin_match = re.search(r"ISIN\s+KODU:\s*([A-Z0-9]+)", body, flags=re.I)
    fee_match = re.search(
        r"Yönetim ücreti[^\n%]{0,80}.*?(\d+(?:[.,]\d+)?)\s*$",
        body,
        flags=re.I | re.M,
    )
    if fee_match is None:
        fee_match = re.search(
            r"Yönetim ücreti\s*\(yıllık\).*?(\d+(?:[.,]\d+)?)",
            body,
            flags=re.I | re.S,
        )
    fee = None
    if fee_match:
        try:
            fee = float(fee_match.group(1).replace(",", "."))
        except ValueError:
            fee = None
    currency = None
    if re.search(r"para birimi\s+TL", body, flags=re.I):
        currency = "TRY"
    return {
        "isin": isin_match.group(1).upper() if isin_match else None,
        "katilim_fonu_status": bool(re.search(r"katılım fonu statüsündedir", body, flags=re.I)),
        "participation_principles": bool(
            re.search(r"katılım prensiplerine uygunluğu esas almış", body, flags=re.I)
        ),
        "katilim_finans_ilkeleri": bool(
            re.search(r"faizsiz/katılım finans ilkelerine uygun", body, flags=re.I)
        ),
        "currency": currency,
        "management_fee_annual_pct": fee,
        "max_maturity_184": bool(re.search(r"vadesine en fazla 184 gün", body, flags=re.I)),
        "avg_maturity_45": bool(re.search(r"ağırlıklı ortalama vadesi 45 günü aşamaz", body, flags=re.I)),
        "min_80_equity_katilim_index": bool(
            re.search(r"en az %80.*BIST Katılım 100", body, flags=re.I | re.S)
        ),
        "min_80_kira_sertifikasi": bool(
            re.search(r"en az %80.*kira sertifikalar", body, flags=re.I | re.S)
        ),
        "tl_assets_only": bool(re.search(r"sadece TL cinsi varlıklar", body, flags=re.I)),
    }


def official_profile_from_kap(
    *,
    umbrella_type: Optional[str],
    ybf: Mapping[str, Any],
) -> Optional[str]:
    """Profile from official KAP type + YBF mandate facts. Not from the fund name."""
    facts = dict(ybf or {})
    if facts.get("max_maturity_184") and facts.get("avg_maturity_45"):
        return PROFILE_SHORT_TERM_PARTICIPATION
    if facts.get("min_80_equity_katilim_index"):
        return PROFILE_PARTICIPATION_EQUITY
    if facts.get("min_80_kira_sertifikasi"):
        return PROFILE_SUKUK_LEASE_CERTIFICATE
    _ = umbrella_type
    return None


def parse_kap_mandate(
    *,
    fund_code: str,
    ozet_fields: Mapping[str, str],
    ybf_text: str = "",
    ybf_payload: Optional[Mapping[str, Any]] = None,
    source_url: str = "",
    ybf_url: str = "",
    as_of: Optional[str] = None,
) -> KapFundMandateEvidence:
    code = normalize_fund_code(fund_code)
    ozet = dict(ozet_fields or {})
    parsed = parse_kap_ybf_text(ybf_text) if ybf_text else {}
    ybf = dict(ybf_payload or {})
    umbrella_type = ozet.get(OZET_LABEL_UMBRELLA_TYPE)
    merged_ybf = {
        "max_maturity_184": parsed.get("max_maturity_184")
        or bool(re.search(r"184 gün", str(ybf.get("strategy") or ""), flags=re.I)),
        "avg_maturity_45": parsed.get("avg_maturity_45")
        or bool(re.search(r"45 günü aşamaz", str(ybf.get("strategy") or ""), flags=re.I)),
        "min_80_equity_katilim_index": parsed.get("min_80_equity_katilim_index")
        or bool(re.search(r"BIST Katılım 100", str(ybf.get("strategy") or ""), flags=re.I)),
        "min_80_kira_sertifikasi": parsed.get("min_80_kira_sertifikasi")
        or bool(re.search(r"kira sertifikalar", str(ybf.get("strategy") or ""), flags=re.I)),
    }
    wording: list[str] = []
    status = str(ybf.get("status_sentence") or "")
    if status:
        wording.append(status)
    elif parsed.get("katilim_fonu_status"):
        wording.append("katılım fonu statüsündedir")
    if parsed.get("participation_principles") or "katılım prensiplerine" in status.lower():
        wording.append("katılım prensiplerine uygunluğu esas almış")
    strategy = str(ybf.get("strategy") or "").strip() or None
    if strategy and "faizsiz/katılım finans ilkelerine uygun" in strategy.lower():
        wording.append("faizsiz/katılım finans ilkelerine uygun")
    allowed: list[str] = []
    if merged_ybf["min_80_equity_katilim_index"]:
        allowed.append("BIST Katılım 100 ortaklık payları")
    if merged_ybf["min_80_kira_sertifikasi"]:
        allowed.append("kamu ve özel sektör kira sertifikaları")
    if merged_ybf["max_maturity_184"]:
        allowed.append("vadesine en fazla 184 gün kalmış faize dayalı olmayan araçlar")
    currency = None
    currency_sentence = str(ybf.get("currency_sentence") or "")
    if "TL" in currency_sentence or parsed.get("currency") == "TRY":
        currency = "TRY"
    if parsed.get("tl_assets_only") or "sadece TL cinsi varlıklar" in (strategy or ""):
        currency = "TRY"
    fee = ybf.get("management_fee_annual_pct")
    if fee is None:
        fee = parsed.get("management_fee_annual_pct")
    excerpts = tuple(
        item
        for item in (
            status or None,
            strategy,
            currency_sentence or None,
            str(ybf.get("benchmark") or "") or None,
        )
        if item
    )
    return KapFundMandateEvidence(
        fund_code=code,
        official_name=str(ybf.get("official_name") or "") or None,
        umbrella_name=ozet.get(OZET_LABEL_UMBRELLA_NAME),
        umbrella_type=umbrella_type,
        founder=ozet.get(OZET_LABEL_FOUNDER),
        portfolio_manager=str(ybf.get("portfolio_manager") or "") or None,
        strategy_text=strategy,
        participation_wording=tuple(dict.fromkeys(wording)),
        allowed_asset_classes=tuple(allowed),
        currency_restriction=currency,
        maturity_restriction=(
            "max 184 days to maturity; weighted average maturity <= 45 days"
            if merged_ybf["max_maturity_184"] and merged_ybf["avg_maturity_45"]
            else None
        ),
        minimum_equity_allocation="80% BIST Katılım 100" if merged_ybf["min_80_equity_katilim_index"] else None,
        sukuk_mandate=(
            "min 80% Hazine and private-sector kira sertifikaları"
            if merged_ybf["min_80_kira_sertifikasi"]
            else None
        ),
        benchmark=str(ybf.get("benchmark") or "") or None,
        management_fee_annual_pct=float(fee) if fee is not None else None,
        official_profile=official_profile_from_kap(umbrella_type=umbrella_type, ybf=merged_ybf),
        source=PROVIDER_KAP_FUND,
        source_url=ybf_url or source_url,
        as_of=as_of or str(ybf.get("as_of") or "") or None,
        excerpts=excerpts,
        limitations=("RAW_OFFICIAL_TEXT_ONLY",),
    )


def parse_kap_portfolio_report_audit(
    *,
    fund_code: str,
    report: Mapping[str, Any],
) -> KapPortfolioReportAudit:
    code = normalize_fund_code(fund_code)
    payload = dict(report or {})
    latest = str(payload.get("disclosure_url") or payload.get("file_url") or "") or None
    found = bool(latest)
    exact = (
        PDR_FIELD_ASSET_WEIGHTS,
        PDR_FIELD_HOLDINGS,
        PDR_FIELD_ISSUER,
        PDR_FIELD_ISIN,
        PDR_FIELD_MATURITY,
        PDR_FIELD_CURRENCY,
    )
    limitations = []
    if not found:
        limitations.append("LATEST_DISCLOSURE_ID_NOT_STATIC")
    limitations.append("NO_HOLDINGS_PARSER")
    limitations.append("COUNTRY_FIELD_NOT_IN_PDR_TEMPLATE")
    return KapPortfolioReportAudit(
        fund_code=code,
        latest_report_title=str(payload.get("title") or "") or None,
        latest_report_url=latest,
        period=str(payload.get("period") or "") or None,
        asset_weights=True,
        holdings=True,
        issuer=True,
        maturity=True,
        currency=True,
        country=False,
        lookthrough=False,
        exact_fields=exact,
        source=PROVIDER_KAP_FUND,
        source_url=latest or f"{KAP_HOST}/tr/fon-bildirimleri/{code.lower()}",
        limitations=tuple(limitations),
    )
