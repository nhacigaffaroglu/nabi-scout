"""Parse official public KAP KAFİF HTML. No ratio recomputation."""

from __future__ import annotations

import re
from typing import Optional

from services.kap_kafif_contract import (
    ANSWER_EVET,
    ANSWER_HAYIR,
    KAFIF_FORM_TITLE,
    LIMITATION_STRUCTURE,
    SOURCE_PUBLIC_KAP_KAFIF,
    KapKafifDiscovery,
    KapKafifDocument,
    KapKafifSourceError,
    kafif_bildirim_url,
)
from services.kap_public_contract import KAP_PUBLIC_HOST


_Q1 = "esas sözleşmesinde yer alan faaliyet alanları"
_Q2 = "uygun olmayan imtiyaz"
_Q3 = "standart madde 1.5"
_Q4 = "doğrudan katılım finansı ilkelerine aykırı"
_R5 = "uygun olmayan gelirlerinin oranı"
_R6 = "uygun olmayan varlıklarının oranı"
_R7 = "uygun olmayan borçlarının oranı"


def parse_tr_decimal(raw: object) -> Optional[float]:
    text = str(raw or "").strip().replace("%", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    try:
        return float(text)
    except ValueError:
        return None


def parse_evet_hayir(raw: object) -> tuple[str, Optional[bool]]:
    text = str(raw or "").strip().upper()
    if text == ANSWER_EVET:
        return ANSWER_EVET, True
    if text == ANSWER_HAYIR:
        return ANSWER_HAYIR, False
    return str(raw or "").strip(), None


def normalize_kafif_period(year: str, period_raw: str) -> str:
    period = str(period_raw or "").strip()
    year = str(year or "").strip()
    if "6" in period and "Aylık" in period:
        return "YTD"
    if period in {"Yıllık", "Yillik"}:
        return "FY"
    if "3" in period and "Aylık" in period:
        return "Q"
    if "9" in period and "Aylık" in period:
        return "YTD"
    return period or year


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(td|tr|div|p|h\d)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"[ \t]+", " ", text)


def _fold(text: str) -> str:
    return str(text or "").replace("İ", "i").replace("I", "i").lower()


def _field_after(text: str, label: str) -> str:
    pattern = re.compile(
        re.escape(label) + r"\s*[:\n]?\s*([^\n]+)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _answer_for(text: str, token: str) -> str:
    idx = _fold(text).find(_fold(token))
    if idx < 0:
        return ""
    window = text[idx : idx + 400]
    match = re.search(r"\b(EVET|HAYIR)\b", window, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _ratio_for(text: str, token: str) -> str:
    idx = _fold(text).find(_fold(token))
    if idx < 0:
        return ""
    window = text[idx : idx + 280]
    after_formula = window.split("* 100", 1)[-1] if "* 100" in window else window
    match = re.search(r"(\d+(?:[.,]\d+)?)", after_formula)
    return match.group(1) if match else ""


def parse_kafif_disclosure_index(html: str) -> tuple[KapKafifDiscovery, ...]:
    """Read public KAP member-search rows. Checkbox id is the Bildirim id."""
    found: list[KapKafifDiscovery] = []
    row_re = re.compile(
        r'<input[^>]+id="(\d+)"[^>]*>.*?(?:Katılım Finansı İlkeleri Bilgi Formu)',
        re.IGNORECASE | re.DOTALL,
    )
    for match in row_re.finditer(html):
        disclosure_id = match.group(1)
        chunk = match.group(0)
        symbol_match = re.search(r">\s*([A-Z]{3,6})\s*<", chunk)
        year_match = re.search(r">\s*(20\d{2})\s*<", chunk)
        period_match = re.search(r">\s*(\d+\s*Aylık|Yıllık)\s*<", chunk, re.IGNORECASE)
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", chunk)
        found.append(
            KapKafifDiscovery(
                symbol=(symbol_match.group(1) if symbol_match else "").upper(),
                disclosure_id=disclosure_id,
                submitted_at=date_match.group(1) if date_match else "",
                financial_year=year_match.group(1) if year_match else "",
                period=period_match.group(1) if period_match else "",
                source_url=kafif_bildirim_url(disclosure_id),
            )
        )
    return tuple(found)


def latest_kafif_discovery(rows: tuple[KapKafifDiscovery, ...]) -> Optional[KapKafifDiscovery]:
    if not rows:
        return None

    def sort_key(row: KapKafifDiscovery) -> tuple[str, str]:
        parts = row.submitted_at.split(".")
        if len(parts) == 3:
            return (f"{parts[2]}-{parts[1]}-{parts[0]}", row.disclosure_id)
        return (row.submitted_at, row.disclosure_id)

    return sorted(rows, key=sort_key, reverse=True)[0]


def parse_public_kafif_html(
    html: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str = "",
) -> KapKafifDocument:
    if KAFIF_FORM_TITLE not in html and "tbl_KFIF-General-Info-Form" not in html:
        raise KapKafifSourceError(LIMITATION_STRUCTURE)

    text = _strip_tags(html)
    issuer = ""
    issuer_match = re.search(
        r"([A-ZÇĞİÖŞÜa-zçğıöşü0-9\s\-\.]+A\.Ş\.)",
        text,
    )
    if issuer_match:
        issuer = issuer_match.group(1).strip()

    submitted = _field_after(text, "Gönderim Tarihi")
    year = _field_after(text, "Yıl")
    period_raw = _field_after(text, "Periyot")
    if not year:
        year_match = re.search(r"(20\d{2})\s*/\s*\d+\s*Aylık", text)
        year = year_match.group(1) if year_match else ""
    if not period_raw:
        period_match = re.search(r"20\d{2}\s*/\s*(\d+\s*Aylık|Yıllık)", text)
        period_raw = period_match.group(1) if period_match else ""

    unit = _field_after(text, "Sunum Para Birimi")
    consolidation = _field_after(text, "Finansal Tablo Niteliği")
    period_combo = _field_after(text, "Verilerin Ait Olduğu Finansal Tablo Yılı / Dönemi")
    if period_combo and "/" in period_combo:
        left, right = [part.strip() for part in period_combo.split("/", 1)]
        year = year or left
        period_raw = period_raw or right

    q1_raw, q1 = parse_evet_hayir(_answer_for(text, _Q1))
    q2_raw, q2 = parse_evet_hayir(_answer_for(text, _Q2))
    q3_raw, q3 = parse_evet_hayir(_answer_for(text, _Q3))
    q4_raw, q4 = parse_evet_hayir(_answer_for(text, _Q4))
    r5_raw = _ratio_for(text, _R5)
    r6_raw = _ratio_for(text, _R6)
    r7_raw = _ratio_for(text, _R7)

    currency = "TRY" if "TL" in unit.upper() or unit.upper() == "TRY" else unit.upper()
    consolidated = None
    if consolidation.lower().startswith("konsolide olmayan"):
        consolidated = False
    elif consolidation.lower().startswith("konsolide"):
        consolidated = True

    complete = all(
        value is not None
        for value in (q1, q2, q3, q4, parse_tr_decimal(r5_raw), parse_tr_decimal(r6_raw), parse_tr_decimal(r7_raw))
    )

    return KapKafifDocument(
        symbol=str(symbol or "").strip().upper(),
        issuer_name=issuer,
        disclosure_id=str(disclosure_id),
        submitted_at=submitted,
        financial_year=year,
        period=normalize_kafif_period(year, period_raw),
        period_raw=period_raw or period_combo,
        consolidated=consolidated,
        consolidation_raw=consolidation,
        presentation_currency=currency or "TRY",
        presentation_unit_label=unit,
        source_url=source_url or kafif_bildirim_url(disclosure_id),
        q1_unsuitable_activity_raw=q1_raw,
        q2_unsuitable_privilege_raw=q2_raw,
        q3_prohibited_support_raw=q3_raw,
        q4_direct_non_compliant_raw=q4_raw,
        q1_unsuitable_activity=q1,
        q2_unsuitable_privilege=q2,
        q3_prohibited_support=q3,
        q4_direct_non_compliant=q4,
        non_compliant_income_ratio_raw=r5_raw,
        non_compliant_asset_ratio_raw=r6_raw,
        non_compliant_debt_ratio_raw=r7_raw,
        non_compliant_income_ratio=parse_tr_decimal(r5_raw),
        non_compliant_asset_ratio=parse_tr_decimal(r6_raw),
        non_compliant_debt_ratio=parse_tr_decimal(r7_raw),
        complete=complete,
        provenance={
            "source": SOURCE_PUBLIC_KAP_KAFIF,
            "host": KAP_PUBLIC_HOST,
            "official_ratios_not_recomputed": True,
        },
    )
