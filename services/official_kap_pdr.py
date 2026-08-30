"""Official KAP Portföy Dağılım Raporu discovery and holdings parser.

Narrow Turkish PDR layer. Reuses FundFacts / OfficialHolding / look-through
weight rules. Does not score Fund Intelligence or Participation.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from services.bist_symbol_mapping import normalize_bist_symbol
from services.fund_lookthrough_summary import build_fund_lookthrough_summary
from services.fund_product_contract import (
    ASSET_GROUP_CASH,
    ASSET_GROUP_DERIVATIVE,
    ASSET_GROUP_EQUITY,
    ASSET_GROUP_FUND,
    ASSET_GROUP_LEASE_CERTIFICATE,
    ASSET_GROUP_OTHER,
    ASSET_GROUP_PARTICIPATION_ACCOUNT,
    ASSET_GROUP_REPO,
    ASSET_GROUP_UNKNOWN,
    KAP_FUNDS_BY_CRITERIA,
    KapPdrDiscovery,
    KapPdrHolding,
    KapPdrHoldingsFile,
    KapPdrLookthroughReadiness,
    KapPdrSecurityMasterOverlap,
    KapPdrWeightReconciliation,
    PDR_SUBJECT,
    PROVIDER_KAP_FUND,
)
from services.official_fund_holdings_client import (
    MATERIAL_WEIGHT_MAX_PCT,
    MATERIAL_WEIGHT_MIN_PCT,
    OfficialHolding,
    OfficialHoldingsFile,
)
from services.official_tefas import normalize_fund_code

try:
    from services.official_kap_fund import KAP_HOST as _KAP_HOST
except ImportError:  # pragma: no cover
    _KAP_HOST = "https://www.kap.org.tr"

KAP_HOST = _KAP_HOST
PDR_DISCOVERY_URL = f"{KAP_HOST}{KAP_FUNDS_BY_CRITERIA}"
PROVENANCE_KAP_PDR = "kap_pdr_official"

_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")
_BIST_CODE_RE = re.compile(r"\b([A-Z0-9]{2,6}\.[EF])\b")
_TR_DATE_RE = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{2,4})\b")
_FILE_RE = re.compile(
    r"/tr/api/file/download/([0-9a-f]+).*?([\w.\- ]+\.pdf)",
    flags=re.I | re.S,
)
_FILE_RE_REV = re.compile(
    r"([\w.\- ]+\.pdf).*?/tr/api/file/download/([0-9a-f]+)",
    flags=re.I | re.S,
)
_NUM_TOKEN = re.compile(
    r"-?\d{1,3}(?:\.\d{3})+,\d+|-?\d+,\d+|-?\d{1,3}(?:\.\d{3})+|-?\d+"
)

_SECTION_MAP = (
    ("kamu kesimi kira", ASSET_GROUP_LEASE_CERTIFICATE),
    ("özel sektör kira", ASSET_GROUP_LEASE_CERTIFICATE),
    ("kira sertifika", ASSET_GROUP_LEASE_CERTIFICATE),
    ("katılım hesabı", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("katilim hesabi", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("taahhüt sözleşmesi", ASSET_GROUP_REPO),
    ("taahhut sozlesmesi", ASSET_GROUP_REPO),
    ("satış vaadiyle alış", ASSET_GROUP_REPO),
    ("satis vaadiyle alis", ASSET_GROUP_REPO),
    ("hisse senet", ASSET_GROUP_EQUITY),
    ("borsa yatırım fonu", ASSET_GROUP_FUND),
    ("yatırım fonu", ASSET_GROUP_FUND),
    ("katılma pay", ASSET_GROUP_FUND),
    ("hazır değer", ASSET_GROUP_CASH),
    ("hazir deger", ASSET_GROUP_CASH),
    ("opsiyon", ASSET_GROUP_DERIVATIVE),
    ("türev", ASSET_GROUP_DERIVATIVE),
    ("borçlar", ASSET_GROUP_OTHER),
    ("borclar", ASSET_GROUP_OTHER),
    ("alacaklar", ASSET_GROUP_OTHER),
)

_TR_FOLD = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ş": "s",
        "ş": "s",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
    }
)


def _fold(text: Any) -> str:
    return str(text or "").translate(_TR_FOLD).casefold()


_HEADER_SKIP = (
    "i-fonu",
    "ii-fonun",
    "iii-fon",
    "iv-fon",
    "v-ay",
    "vi-a",
    "vii-",
    "viii-",
    "ix-",
    "isin kodu",
    "toplam (fpd",
    "grup (%)",
    "1 - fonu",
    "2 - fonun",
    "3 - fon portföy",
    "4 - toplam",
    "5 - ay içinde",
    "7 - portföyden",
    "8 - itfalar",
    "9 - portföye",
)


class KapPdrError(RuntimeError):
    pass


def report_period_label(year: Any, period: Any) -> Optional[str]:
    try:
        y = int(year)
        p = int(period)
    except (TypeError, ValueError):
        return None
    if y < 1990 or p < 1 or p > 12:
        return None
    return f" {y}-{p:02d}".strip()


def parse_tr_number(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(" ", "").replace("%", "")
    if not text or text in {":", "-", "—"}:
        return None
    if re.fullmatch(r"-?\d+\.\d+", text) and text.count(".") == 1 and "," not in text:
        try:
            return float(text)
        except ValueError:
            return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_tr_date(raw: Any) -> Optional[str]:
    text = str(raw or "").strip()
    match = _TR_DATE_RE.search(text)
    if not match:
        return None
    token = match.group(1).replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(token, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_tr_datetime(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if ":" in text else text[:10], fmt)
        except ValueError:
            continue
    return None


def normalize_pdr_asset_group(raw_label: Any) -> str:
    label = str(raw_label or "").strip()
    if not label:
        return ASSET_GROUP_UNKNOWN
    folded = _fold(label)
    for needle, group in _SECTION_MAP:
        if _fold(needle) in folded:
            return group
    return ASSET_GROUP_UNKNOWN


def parse_pdr_attachment_html(html: str) -> tuple[Optional[str], Optional[str]]:
    body = str(html or "")
    match = _FILE_RE.search(body)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    match = _FILE_RE_REV.search(body)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, None


def _is_pdr_row(row: Mapping[str, Any], fund_code: str) -> bool:
    code = normalize_fund_code(row.get("fundCode"))
    subject = str(row.get("subject") or "").strip()
    return code == fund_code and subject == PDR_SUBJECT


def _discovery_sort_key(row: Mapping[str, Any]) -> tuple:
    year = int(row.get("year") or 0)
    period = int(row.get("period") or 0)
    published = parse_tr_datetime(row.get("publishDate")) or datetime.min
    index = int(row.get("disclosureIndex") or 0)
    return (year, period, published, index)


def discover_latest_pdr(
    rows: Sequence[Mapping[str, Any]],
    fund_code: str,
    *,
    attachments: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> KapPdrDiscovery:
    code = normalize_fund_code(fund_code)
    matches = [dict(row) for row in rows if _is_pdr_row(row, code)]
    if not matches:
        return KapPdrDiscovery(
            fund_code=code,
            year=None,
            period=None,
            report_period=None,
            publish_date=None,
            disclosure_index=None,
            subject=PDR_SUBJECT,
            disclosure_class=None,
            attachment_name=None,
            attachment_file_id=None,
            source_url=PDR_DISCOVERY_URL,
            file_url=None,
            resolved=False,
            limitations=("LATEST_PDR_UNRESOLVED",),
        )
    latest = max(matches, key=_discovery_sort_key)
    year = latest.get("year")
    period = latest.get("period")
    if year in (None, "") or period in (None, "", 0):
        return KapPdrDiscovery(
            fund_code=code,
            year=int(year) if year not in (None, "") else None,
            period=int(period) if period not in (None, "", 0) else None,
            report_period=None,
            publish_date=str(latest.get("publishDate") or "") or None,
            disclosure_index=int(latest["disclosureIndex"]) if latest.get("disclosureIndex") else None,
            subject=PDR_SUBJECT,
            disclosure_class=str(latest.get("disclosureClass") or "") or None,
            attachment_name=None,
            attachment_file_id=None,
            source_url=PDR_DISCOVERY_URL,
            file_url=None,
            resolved=False,
            limitations=("PDR_PERIOD_MISSING",),
        )
    index = int(latest["disclosureIndex"])
    attach_name = None
    attach_id = None
    extra = dict((attachments or {}).get(code) or {})
    if extra.get("html_excerpt"):
        attach_name, attach_id = parse_pdr_attachment_html(str(extra.get("html_excerpt")))
    if extra.get("attachment_name"):
        attach_name = str(extra.get("attachment_name"))
    if extra.get("attachment_file_id"):
        attach_id = str(extra.get("attachment_file_id"))
    file_url = f"{KAP_HOST}/tr/api/file/download/{attach_id}" if attach_id else None
    return KapPdrDiscovery(
        fund_code=code,
        year=int(year),
        period=int(period),
        report_period=report_period_label(year, period),
        publish_date=str(latest.get("publishDate") or "") or None,
        disclosure_index=index,
        subject=PDR_SUBJECT,
        disclosure_class=str(latest.get("disclosureClass") or "") or None,
        attachment_name=attach_name,
        attachment_file_id=attach_id,
        source_url=f"{KAP_HOST}/tr/Bildirim/{index}",
        file_url=file_url,
        resolved=True,
        limitations=(),
    )


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_header(line: str) -> bool:
    folded = _fold(line)
    return any(_fold(prefix) in folded[:48] for prefix in _HEADER_SKIP)


def _section_from_line(line: str) -> Optional[str]:
    folded = _fold(line)
    if "grup toplam" in folded or ("fon portfoy degeri" in folded and "tablosu" not in folded):
        return None
    if _is_header(line) and "kira" not in folded and "katilim" not in folded and "taahhut" not in folded:
        return None
    group = normalize_pdr_asset_group(line)
    if group == ASSET_GROUP_UNKNOWN:
        return None
    if len(_plain(line)) > 80 and _ISIN_RE.search(line):
        return None
    return re.sub(r"^#+\s*", "", line.strip())


def _numbers(text: str) -> list[str]:
    return _NUM_TOKEN.findall(text)


def _holding(
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    asset_group_raw: Optional[str],
    security_name_raw: Optional[str],
    issuer_raw: Optional[str],
    isin: Optional[str],
    official_code: Optional[str],
    maturity_date: Optional[str],
    currency: Optional[str],
    quantity: Optional[float],
    nominal: Optional[float],
    unit_price: Optional[float],
    market_value: Optional[float],
    portfolio_weight: Optional[float],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> KapPdrHolding:
    group = normalize_pdr_asset_group(asset_group_raw)
    if group == ASSET_GROUP_UNKNOWN and official_code:
        if official_code.endswith(".E"):
            group = ASSET_GROUP_EQUITY
        elif official_code.endswith(".F"):
            group = ASSET_GROUP_FUND
    return KapPdrHolding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group=group,
        asset_group_raw=asset_group_raw,
        security_name_raw=security_name_raw,
        issuer_raw=issuer_raw,
        isin=isin,
        official_code=official_code,
        maturity_date=maturity_date,
        currency=currency,
        quantity=quantity,
        nominal=nominal,
        unit_price=unit_price,
        market_value=market_value,
        portfolio_weight=portfolio_weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
        provenance=(PROVENANCE_KAP_PDR, PDR_SUBJECT),
    )


def _parse_isin_row(
    line: str,
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    section: Optional[str],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> Optional[KapPdrHolding]:
    if "GRUP TOPLAMI" in line.upper() or _is_header(line):
        return None
    isins = _ISIN_RE.findall(line)
    if not isins:
        return None
    isin = isins[0]
    ccy = None
    ccy_match = re.search(r"\b(TL|TRY|USD|EUR)\b", line)
    if ccy_match:
        ccy = ccy_match.group(1)
    maturity = parse_tr_date(line)
    issuer = None
    name = None
    after = line
    lead = re.match(
        rf"{re.escape(isin)}\s+(?:{ccy}\s+)?(.+?)\s+{_TR_DATE_RE.pattern}",
        line,
    )
    if lead:
        issuer = _plain(lead.group(1))
        name = isin
    elif ccy:
        mid = re.search(
            rf"{re.escape(isin)}\s+(.+?)\s+{ccy}\s+{_TR_DATE_RE.pattern}",
            line,
        )
        if mid:
            issuer = _plain(mid.group(1))
            name = isin
    if issuer:
        issuer = re.sub(r"\s+\b(TL|TRY|USD|EUR)\b\s*$", "", issuer).strip() or issuer
    nums = _numbers(line)
    weight = None
    market_value = None
    nominal = None
    unit_price = None
    if len(nums) >= 4:
        parsed = [parse_tr_number(tok) for tok in nums]
        values = [item for item in parsed if item is not None]
        pcts = [item for item in values if abs(item) <= 100]
        if len(values) >= 3 and all(abs(item) <= 100 for item in values[-3:]):
            weight = values[-1]
            market_value = next(
                (item for item in reversed(values[:-3]) if abs(item) >= 1),
                None,
            )
        elif pcts:
            weight = pcts[-1]
            market_value = next((item for item in reversed(values) if abs(item) > 100), None)
        if len(values) >= 6:
            candidates = [item for item in values if item >= 100]
            if candidates:
                nominal = candidates[0]
            prices = [item for item in values if 1 < item < 200]
            if prices:
                unit_price = prices[0]
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=name,
        issuer_raw=issuer,
        isin=isin,
        official_code=isin,
        maturity_date=maturity,
        currency=ccy,
        quantity=None,
        nominal=nominal,
        unit_price=unit_price,
        market_value=market_value,
        portfolio_weight=weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


def _parse_deposit_row(
    line: str,
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    section: Optional[str],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> Optional[KapPdrHolding]:
    if _ISIN_RE.search(line) or "GRUP TOPLAMI" in line.upper():
        return None
    if not re.search(r"\bTL\b", line):
        return None
    if not _TR_DATE_RE.search(line):
        return None
    nums = _numbers(line)
    if len(nums) < 4:
        return None
    issuer = _plain(re.split(r"\bTL\b", line, maxsplit=1)[0])
    if not issuer or len(issuer) < 3:
        return None
    values = [parse_tr_number(tok) for tok in nums]
    compact = [item for item in values if item is not None]
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section or "KATILIM HESABI",
        security_name_raw=issuer,
        issuer_raw=issuer,
        isin=None,
        official_code=None,
        maturity_date=parse_tr_date(line),
        currency="TL",
        quantity=None,
        nominal=compact[1] if len(compact) > 1 and compact[1] and compact[1] > 100 else compact[0] if compact else None,
        unit_price=None,
        market_value=next((item for item in reversed(compact[:-3]) if item and abs(item) >= 1), None)
        if len(compact) >= 4
        else None,
        portfolio_weight=compact[-1] if compact else None,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


def _parse_zpe_equity_row(
    line: str,
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> Optional[KapPdrHolding]:
    match = re.search(
        r"(?P<n>\d+)\s+(?P<code>[A-Z0-9]{2,6}\.[EF])\s+(?P<name>.+?)\s+"
        r"(?P<qty>-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+)\s+"
        r"(?P<mv>-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+)\s+"
        r"(?P<w>-?\d+,\d+)\s+"
        r"(?P<px>-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+)",
        _plain(line.replace("|", " ")),
    )
    if not match:
        return None
    code = match.group("code")
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw="HİSSE SENETLERİ" if code.endswith(".E") else "KATILMA PAYLARI",
        security_name_raw=_plain(match.group("name")),
        issuer_raw=_plain(match.group("name")),
        isin=None,
        official_code=code,
        maturity_date=None,
        currency=None,
        quantity=parse_tr_number(match.group("qty")),
        nominal=None,
        unit_price=parse_tr_number(match.group("px")),
        market_value=parse_tr_number(match.group("mv")),
        portfolio_weight=parse_tr_number(match.group("w")),
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


def _parse_zpe_other_row(
    line: str,
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    section: Optional[str],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> Optional[KapPdrHolding]:
    text = _plain(line)
    if text.startswith(("7 -", "8 -", "9 -", "HS ", "SVDA ", "KTAL ")):
        return None
    nums = _numbers(text)
    if len(nums) < 3:
        return None
    isin = None
    found = _ISIN_RE.search(text)
    if found:
        isin = found.group(1)
    code_match = re.search(r"\b(\dAyaKadarVD-[A-Z]{2,4}-TRY)\b", text)
    official = isin or (code_match.group(1) if code_match else None)
    if not official:
        return None
    money = [parse_tr_number(tok) for tok in nums if "," in tok]
    money = [item for item in money if item is not None]
    issuer = None
    if "HAZİNE" in text:
        issuer = "HAZİNE"
    weight = None
    market_value = None
    nominal = None
    if money:
        last = money[-1]
        small = [item for item in money if abs(item) <= 100]
        large = [item for item in money if abs(item) > 100]
        if abs(last) <= 100:
            weight = last
        elif small:
            weight = small[-1]
        market_value = large[-1] if large else None
        nominal = large[0] if large else None
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=official,
        issuer_raw=issuer,
        isin=isin,
        official_code=official,
        maturity_date=parse_tr_date(text),
        currency="TRY" if "TRY" in text or "HAZİNE" in text else None,
        quantity=None,
        nominal=nominal,
        unit_price=None,
        market_value=market_value if market_value is not None else (money[0] if money else None),
        portfolio_weight=weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


def _parse_ftd_overlay(
    text: str,
    *,
    fund_code: str,
    report_period: Optional[str],
    report_date: Optional[str],
    fund_total_value: Optional[float],
    source_notification_id: Optional[str],
    source_attachment: Optional[str],
) -> list[KapPdrHolding]:
    rows: list[KapPdrHolding] = []
    patterns = (
        (r"B-\)?\s*HAZIR DE[ĞG]ERLER\s+(-?[\d.]+,\d+)\s+(-?[\d,]+)\s*%", "HAZIR DEĞERLER"),
        (r"C-\)?\s*ALACAKLAR\s+(-?[\d.]+,\d+)\s+(-?[\d,]+)\s*%", "ALACAKLAR"),
        (r"E-\)?\s*BOR[ÇC]LAR\s+(-?[\d.]+,\d+)\s+(-?[\d,]+)\s*%", "BORÇLAR"),
    )
    for pattern, label in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        rows.append(
            _holding(
                fund_code=fund_code,
                report_period=report_period,
                report_date=report_date,
                asset_group_raw=label,
                security_name_raw=label,
                issuer_raw=None,
                isin=None,
                official_code=None,
                maturity_date=None,
                currency=None,
                quantity=None,
                nominal=None,
                unit_price=None,
                market_value=parse_tr_number(match.group(1)),
                portfolio_weight=parse_tr_number(match.group(2)),
                fund_total_value=fund_total_value,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
        )
    return rows


_ISIN_HOLDING_SPLIT = re.compile(r"(?=(?:[A-Z]{2}[A-Z0-9]{10})\s+(?:TL|TRY)\s+)")
_SPLIT_IDENTITY = re.compile(
    r"([A-Z]{2}[A-Z0-9]{10})\s+(TL|TRY|USD|EUR)\s+(\S+?)\s+"
    r"(\d{2}/\d{2}/\d{2})\s+(\d+)\s+\1\b"
)
_SPLIT_FTD = re.compile(
    r"(\d{1,3}(?:\.\d{3})+,\d{2})\s+(\d+,\d+)\s+(\d+,\d+)\s+(\d+,\d+)"
)
_SPLIT_NOMINAL = re.compile(
    r"(\d+,\d+)\s+(\d+)\s+(\d{1,3}(?:\.\d{3})+,\d{2})"
)


def _holding_ftd_triple(match: re.Match[str]) -> bool:
    grup = parse_tr_number(match.group(2))
    ftd = parse_tr_number(match.group(4))
    if grup is None or ftd is None:
        return False
    # Official holding triplets stay small; GRUP TOPLAMI is 100 / 58.80 / 59.19.
    return abs(grup) < 20 and abs(ftd) < 10


def reconstruct_split_table_rows(text: str) -> list[str]:
    """Rebuild official rows split across PDF page-break table columns.

    Pair identity fragments with explicit FTD weight fragments only when
    counts match. Do not invent a residual balancer.
    """
    body = str(text or "")
    identities = list(_SPLIT_IDENTITY.finditer(body))
    weights = [m for m in _SPLIT_FTD.finditer(body) if _holding_ftd_triple(m)]
    if not identities or len(identities) != len(weights):
        return []
    noms = list(_SPLIT_NOMINAL.finditer(body))
    rows: list[str] = []
    for idx, ident in enumerate(identities):
        isin, ccy, issuer, maturity, days = ident.groups()
        mv, grup, fpd, ftd = weights[idx].groups()
        extra = ""
        if len(noms) == len(identities):
            rate, pay, nominal = noms[idx].groups()
            extra = f"{rate} {pay} {nominal} "
        rows.append(
            f"{isin} {ccy} {issuer} {maturity} {days} {isin} {extra}{mv} {grup} {fpd} {ftd}"
        )
    return rows


def _prepare_pdr_chunks(body: str) -> list[tuple[Optional[str], str]]:
    """Merge wrapped official rows and split jammed multi-holding lines."""
    chunks: list[tuple[Optional[str], str]] = []
    section: Optional[str] = None
    buf = ""
    pipe_buf: list[str] = []

    def flush_pipes() -> None:
        if not pipe_buf:
            return
        rebuilt = reconstruct_split_table_rows(" ".join(pipe_buf))
        pipe_buf.clear()
        for part in rebuilt:
            chunks.append((section, part))

    def flush() -> None:
        nonlocal buf
        flush_pipes()
        text = _plain(buf)
        buf = ""
        if not text or text.upper().startswith("GRUP TOPLAMI"):
            return
        text = re.split(r"GRUP TOPLAMI", text, flags=re.I)[0].strip()
        if not text:
            return
        parts = [part.strip() for part in _ISIN_HOLDING_SPLIT.split(text) if part.strip()]
        if not parts:
            parts = [text]
        for part in parts:
            if part.upper().startswith("GRUP TOPLAMI"):
                continue
            chunks.append((section, part))

    for raw in body.splitlines():
        line = raw.strip()
        if not line or line in {"|", ":"} or set(line) <= {"|", "-", " "}:
            continue
        if re.search(r"IV-?FON TOPLAM|4 - TOPLAM DE[ĞG]ER|VII-PORTF|7 - PORTF|8 - [İI]TFALAR|9 - PORTF", line, flags=re.I):
            flush()
            break
        header = _section_from_line(line)
        if header and not _ISIN_RE.search(line) and not _BIST_CODE_RE.search(line):
            flush()
            section = header
            continue
        if line.startswith("|") and not _BIST_CODE_RE.search(line):
            pipe_buf.append(line)
            continue
        if _BIST_CODE_RE.search(line):
            flush()
            chunks.append((section, line))
            continue
        if (
            not _ISIN_RE.search(line)
            and re.search(r"\b(TL|TRY)\b", line)
            and _TR_DATE_RE.search(line)
        ):
            buf = f"{buf} {line}".strip() if buf else line
            flush()
            continue
        if _ISIN_RE.search(line) and buf and _ISIN_RE.search(buf) and re.search(r"\b(TL|TRY)\b", buf):
            flush()
            buf = line
            continue
        buf = f"{buf} {line}".strip() if buf else line
    flush()
    return chunks


def _cut_holdings_body(text: str) -> str:
    body = str(text or "")
    end = re.search(
        r"IV-?FON TOPLAM DE[ĞG]ER[İI]|4 - TOPLAM DE[ĞG]ER[İI]|VII-PORTF[ÖO]YDEN|7 - PORTF[ÖO]YDEN",
        body,
        flags=re.I,
    )
    end_at = end.start() if end else len(body)
    if re.search(r"\b[A-Z0-9]{2,6}\.[EF]\b", body[:end_at]):
        return body[:end_at]
    start = re.search(r"III-?FON PORTF[ÖO]Y DE[ĞG]ER[İI] TABLOSU|3 - FON PORTF[ÖO]Y DE[ĞG]ER[İI]", body, flags=re.I)
    if start:
        return body[start.start() : end_at]
    return body[:end_at]


def _fund_total_from_text(text: str) -> Optional[float]:
    match = re.search(
        r"FON TOPLAM DE[ĞG]ER[İI]\s*:?\s*(-?[\d.]+,\d+)",
        text,
        flags=re.I,
    )
    if match:
        return parse_tr_number(match.group(1))
    match = re.search(
        r"Toplam De[ğg]er/Net Varl[ıi]k De[ğg]eri\s*(-?[\d.]+,\d+)",
        text,
        flags=re.I,
    )
    if match:
        return parse_tr_number(match.group(1))
    return None


def parse_kap_pdr_text(
    text: str,
    *,
    fund_code: str,
    report_period: Optional[str] = None,
    report_date: Optional[str] = None,
    source_notification_id: Optional[str] = None,
    source_attachment: Optional[str] = None,
    source_url: str = "",
) -> KapPdrHoldingsFile:
    code = normalize_fund_code(fund_code)
    if not code:
        raise KapPdrError("fund_code is required")
    body = str(text or "")
    if not body.strip():
        raise KapPdrError("empty PDR text")
    fund_total = _fund_total_from_text(body)
    holdings_body = _cut_holdings_body(body)
    holdings: list[KapPdrHolding] = []
    section: Optional[str] = None
    for section, line in _prepare_pdr_chunks(holdings_body):
        zpe = _parse_zpe_equity_row(
            line,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
        if zpe:
            holdings.append(zpe)
            continue
        if section and normalize_pdr_asset_group(section) in {
            ASSET_GROUP_PARTICIPATION_ACCOUNT,
            ASSET_GROUP_REPO,
        } and not _ISIN_RE.search(line):
            other = _parse_zpe_other_row(
                line,
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if other:
                holdings.append(other)
                continue
            deposit = _parse_deposit_row(
                line,
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if deposit:
                holdings.append(deposit)
                continue
        if _ISIN_RE.search(line):
            parsed = _parse_isin_row(
                _plain(line),
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if parsed:
                holdings.append(parsed)
                continue
            other = _parse_zpe_other_row(
                line,
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if other:
                holdings.append(other)
                continue
        if section and normalize_pdr_asset_group(section) == ASSET_GROUP_PARTICIPATION_ACCOUNT:
            deposit = _parse_deposit_row(
                _plain(line),
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if deposit:
                holdings.append(deposit)
    if not holdings:
        # ZPE table may sit before section 3.
        for raw_line in body.splitlines():
            zpe = _parse_zpe_equity_row(
                raw_line,
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if zpe:
                holdings.append(zpe)
        for raw_line in body.splitlines():
            folded = raw_line.casefold()
            if "katılım hesabı" in folded or "satis vaadiyle" in folded or "satış vaadiyle" in folded:
                section = raw_line.strip()
                continue
            other = _parse_zpe_other_row(
                raw_line,
                fund_code=code,
                report_period=report_period,
                report_date=report_date,
                section=section,
                fund_total_value=fund_total,
                source_notification_id=source_notification_id,
                source_attachment=source_attachment,
            )
            if other:
                holdings.append(other)
    holdings.extend(
        _parse_ftd_overlay(
            body,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
    )
    if not holdings:
        raise KapPdrError(f"PDR produced no holdings for {code}")
    weights = reconcile_pdr_weights(holdings)
    return KapPdrHoldingsFile(
        fund_code=code,
        report_period=report_period,
        report_date=report_date,
        fund_total_value=fund_total,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
        holdings=tuple(holdings),
        weights=weights,
        source=PROVIDER_KAP_FUND,
        source_url=source_url or PDR_DISCOVERY_URL,
        limitations=("RAW_OFFICIAL_FIELDS_ONLY", "NO_WEIGHT_RENORMALIZATION"),
    )


def reconcile_pdr_weights(rows: Sequence[KapPdrHolding]) -> KapPdrWeightReconciliation:
    reported = 0.0
    known = 0.0
    unknown = 0.0
    for row in rows:
        if row.portfolio_weight is None:
            continue
        weight = float(row.portfolio_weight)
        reported += weight
        if row.isin or row.official_code:
            known += weight
        else:
            unknown += weight
    reported = round(reported, 4)
    known = round(known, 4)
    unknown = round(unknown, 4)
    residual = round(100.0 - reported, 4)
    return KapPdrWeightReconciliation(
        reported_weight_sum=reported,
        known_weight=known,
        unknown_weight=unknown,
        residual_weight=residual,
        weight_reconciled=MATERIAL_WEIGHT_MIN_PCT <= reported <= MATERIAL_WEIGHT_MAX_PCT,
        renormalized=False,
    )


def pdr_rows_to_official_holdings(file: KapPdrHoldingsFile) -> OfficialHoldingsFile:
    as_of = None
    if file.report_date:
        try:
            as_of = datetime.strptime(file.report_date[:10], "%Y-%m-%d").date()
        except ValueError:
            as_of = None
    if as_of is None and file.report_period:
        try:
            as_of = datetime.strptime(file.report_period + "-01", "%Y-%m-%d").date()
        except ValueError:
            as_of = None
    if as_of is None:
        as_of = datetime(2026, 7, 31).date()
    mapped: list[OfficialHolding] = []
    for row in file.holdings:
        if row.portfolio_weight is None:
            continue
        mapped.append(
            OfficialHolding(
                fund_symbol=file.fund_code,
                as_of=as_of,
                ticker=row.official_code or "",
                cusip_raw=row.isin or "",
                security_name=row.security_name_raw or row.issuer_raw or "",
                weight_pct=float(row.portfolio_weight),
                shares=row.quantity,
                price=row.unit_price,
                market_value=row.market_value,
                net_assets=row.fund_total_value,
                source=PROVIDER_KAP_FUND,
                source_reference=file.source_url,
                asset_type=row.asset_group,
                metadata={
                    "issuer": row.issuer_raw,
                    "asset_group_raw": row.asset_group_raw,
                    "maturity_date": row.maturity_date,
                    "currency": row.currency,
                },
            )
        )
    return OfficialHoldingsFile(
        fund_symbol=file.fund_code,
        as_of=as_of,
        source=PROVIDER_KAP_FUND,
        source_reference=file.source_url,
        http_status=200,
        holdings=tuple(mapped),
        parse_failures=0,
        raw_columns=("isin", "issuer_raw", "official_code", "portfolio_weight"),
    )


def join_pdr_to_security_master(
    file: KapPdrHoldingsFile,
    *,
    isin_index: Optional[Mapping[str, str]] = None,
) -> KapPdrSecurityMasterOverlap:
    """Exact ISIN or existing canonical BIST identifier only. No name matching."""
    index = {str(key).strip().upper(): str(value).strip().upper() for key, value in dict(isin_index or {}).items()}
    matched_symbols: list[str] = []
    unmatched: list[str] = []
    matched_w = 0.0
    unresolved_w = 0.0
    matched_n = 0
    unmatched_n = 0
    for row in file.holdings:
        weight = float(row.portfolio_weight or 0.0)
        symbol = None
        if row.isin:
            symbol = index.get(row.isin.upper())
        if symbol is None and row.official_code:
            symbol = normalize_bist_symbol(row.official_code)
        if symbol is None and row.isin:
            symbol = normalize_bist_symbol(row.isin)
        if symbol:
            matched_n += 1
            matched_w += weight
            matched_symbols.append(symbol)
        else:
            unmatched_n += 1
            unresolved_w += weight
            unmatched.append(row.official_code or row.isin or row.security_name_raw or "UNIDENTIFIED")
    return KapPdrSecurityMasterOverlap(
        fund_code=file.fund_code,
        matched_holdings=matched_n,
        unmatched_holdings=unmatched_n,
        matched_weight=round(matched_w, 4),
        unresolved_weight=round(unresolved_w, 4),
        matched_symbols=tuple(sorted(set(matched_symbols))),
        unmatched_codes=tuple(unmatched),
    )


def pdr_lookthrough_readiness(
    file: KapPdrHoldingsFile,
    *,
    overlap: Optional[KapPdrSecurityMasterOverlap] = None,
) -> KapPdrLookthroughReadiness:
    rows = file.holdings
    has_weights = any(row.portfolio_weight is not None for row in rows)
    maturity_w = sum(float(row.portfolio_weight or 0.0) for row in rows if row.maturity_date)
    issuer_w = sum(float(row.portfolio_weight or 0.0) for row in rows if row.issuer_raw)
    reported = abs(file.weights.reported_weight_sum)
    maturity_ready = reported > 0 and (maturity_w / reported) >= 0.5 if reported else False
    issuer_ready = reported > 0 and (issuer_w / reported) >= 0.5 if reported else False
    overlap_ready = bool(overlap and overlap.matched_holdings > 0)
    limitations = []
    if not has_weights:
        limitations.append("WEIGHTS_MISSING")
    if not maturity_ready:
        limitations.append("MATURITY_COVERAGE_PARTIAL")
    if not issuer_ready:
        limitations.append("ISSUER_COVERAGE_PARTIAL")
    if overlap is None:
        limitations.append("SECURITY_MASTER_OVERLAP_NOT_RUN")
    elif not overlap_ready:
        limitations.append("SECURITY_MASTER_NO_EXACT_MATCH")
    return KapPdrLookthroughReadiness(
        fund_code=file.fund_code,
        diversification_ready=has_weights and len(rows) > 0,
        concentration_ready=has_weights and len(rows) > 0,
        maturity_ready=maturity_ready,
        issuer_concentration_ready=issuer_ready,
        security_master_overlap_ready=overlap_ready,
        limitations=tuple(limitations),
    )


def pdr_lookthrough_summary(file: KapPdrHoldingsFile, *, known_nabi_symbols: Optional[Sequence[str]] = None):
    return build_fund_lookthrough_summary(
        pdr_rows_to_official_holdings(file),
        known_nabi_symbols=known_nabi_symbols,
    )


def asset_group_weights(file: KapPdrHoldingsFile) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for row in file.holdings:
        if row.portfolio_weight is None:
            continue
        buckets[row.asset_group] = round(buckets.get(row.asset_group, 0.0) + float(row.portfolio_weight), 4)
    return buckets


def explicit_subgroup_weights(file: KapPdrHoldingsFile, needle: str) -> float:
    total = 0.0
    folded = needle.casefold()
    for row in file.holdings:
        raw = str(row.asset_group_raw or "").casefold()
        if folded in raw and row.portfolio_weight is not None:
            total += float(row.portfolio_weight)
    return round(total, 4)


def largest_holding(file: KapPdrHoldingsFile) -> Optional[KapPdrHolding]:
    ranked = [row for row in file.holdings if row.portfolio_weight is not None]
    if not ranked:
        return None
    return max(ranked, key=lambda row: float(row.portfolio_weight or 0.0))


def top_holdings(file: KapPdrHoldingsFile, n: int = 10) -> tuple[KapPdrHolding, ...]:
    ranked = [row for row in file.holdings if row.portfolio_weight is not None]
    ranked.sort(key=lambda row: float(row.portfolio_weight or 0.0), reverse=True)
    return tuple(ranked[:n])


def issuer_count(file: KapPdrHoldingsFile) -> int:
    names = {str(row.issuer_raw).strip() for row in file.holdings if row.issuer_raw}
    return len(names)


def coverage_ratio(file: KapPdrHoldingsFile, predicate) -> float:
    weights = [float(row.portfolio_weight) for row in file.holdings if row.portfolio_weight is not None]
    if not weights:
        return 0.0
    denom = sum(abs(item) for item in weights) or 1.0
    numer = sum(abs(float(row.portfolio_weight or 0.0)) for row in file.holdings if row.portfolio_weight is not None and predicate(row))
    return round(numer / denom, 4)
