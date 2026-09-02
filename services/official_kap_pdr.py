"""Official KAP Portföy Dağılım Raporu discovery and holdings parser.

Narrow Turkish PDR layer. Reuses FundFacts / OfficialHolding / look-through
weight rules. Does not score Fund Intelligence or Participation.
"""

from __future__ import annotations

import re
from datetime import date, datetime
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
    ASSET_GROUP_PRECIOUS_METALS,
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
_GLUED_ISIN = re.compile(r"(?<=\d)(TR[A-Z0-9]{10})\b")
_BIST_CODE_RE = re.compile(r"\b([A-Z0-9]{2,6}\.[EF])\b")
_TICKER_ROW_RE = re.compile(r"\b([A-Z]{3,6}(?:-[A-Z0-9]{2,10})?)\s+(TL|TRY|USD|EUR|AU1)\b")

_OCR_EQUITY_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9ÇçĞğİıÖöŞşÜü]{2,8}\.E)(?![A-Za-z0-9])"
)


def _ocr_equity_code(line: str, section: Optional[str]) -> Optional[str]:
    """Recognize an OCR-damaged BIST .E token without inventing its identity.

    Recovery is intentionally narrow:
    - only inside the canonical EQUITY section,
    - requires an explicit ``.E`` security token,
    - requires at least two marked KAP percentage columns.

    The returned token is the official text-layer value exactly as captured.
    No OCR character substitution is performed here.
    """
    if normalize_pdr_asset_group(section) != ASSET_GROUP_EQUITY:
        return None

    text = _plain(line)
    match = _OCR_EQUITY_CODE_RE.search(text)
    if not match:
        return None

    explicit_pcts = re.findall(r"-?\d+(?:[.,]\d+)?\s*%", text)
    if len(explicit_pcts) < 2:
        return None

    return match.group(1)

_FTD_TAIL_RE = re.compile(r"(-?\d+,\d+)\s+(-?\d+,\d+)\s+(-?\d+,\d+)\s*$")
_FTD_ROW_RE = re.compile(
    r"(?P<mv>-?\d{1,3}(?:\.\d{3})+,\d{2})\s+"
    r"(?P<grup>-?\d+,\d+)\s+"
    r"(?P<fpd>-?\d+,\d+)\s+"
    r"(?P<ftd>-?\d+,\d+)"
)
_NUMBERED_MONEY = r"(?P<{name}>-?\d{{1,3}}(?:\.\d{{3}})*(?:,\d+)?|-?\d+,\d+)"
_NUMBERED_WEIGHT = r"(?P<wsign>-)?%(?P<w>-?\d+,\d+)(?:\s+\S.*)?$"
_NUMBERED_HOLDING_RE = re.compile(
    r"^(?P<code>[A-Z]{3,6}(?:[A-Z0-9]{1,2})?)\s+(?P<name>.+?)\s+"
    + _NUMBERED_MONEY.format(name="nom")
    + r"\s+"
    + _NUMBERED_MONEY.format(name="mv")
    + r"\s+"
    + _NUMBERED_WEIGHT
)
_NUMBERED_NAMED_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    + _NUMBERED_MONEY.format(name="nom")
    + r"\s+"
    + _NUMBERED_MONEY.format(name="mv")
    + r"\s+"
    + _NUMBERED_WEIGHT
)
_NUMBERED_TAIL_RE = re.compile(
    r"(-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+,\d+)\s+"
    r"(-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+,\d+)\s+"
    r"-?%-?\d+,\d+\s*$"
)
_PAGE_NOISE_RE = re.compile(
    r"temmuz-\d{4}|kamuyu aydinlatma|sayfa\s*\d|menkul kiymet\s+cinsi|doviz\s+ihracci",
    flags=re.I,
)
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
    r"(?<![A-Za-z0-9])"
    r"-?(?:"
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+[.,]\d+"
    r"|\d+"
    r")"
    r"%?"
    r"(?![A-Za-z0-9])"
)
_SECTION_MAP = (
    ("kamu kesimi kira", ASSET_GROUP_LEASE_CERTIFICATE),
    ("özel sektör kira", ASSET_GROUP_LEASE_CERTIFICATE),
    ("kira sertifika", ASSET_GROUP_LEASE_CERTIFICATE),
    ("katılım hesabı", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("katilim hesabi", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("katılma hesap", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("katilma hesap", ASSET_GROUP_PARTICIPATION_ACCOUNT),
    ("katılma belge", ASSET_GROUP_FUND),
    ("katilma belge", ASSET_GROUP_FUND),
    ("taahhüt sözleşmesi", ASSET_GROUP_REPO),
    ("taahhut sozlesmesi", ASSET_GROUP_REPO),
    ("satış vaadiyle alış", ASSET_GROUP_REPO),
    ("satis vaadiyle alis", ASSET_GROUP_REPO),
    ("kıymetli maden", ASSET_GROUP_PRECIOUS_METALS),
    ("kiymetli maden", ASSET_GROUP_PRECIOUS_METALS),
    ("altın", ASSET_GROUP_PRECIOUS_METALS),
    ("altin", ASSET_GROUP_PRECIOUS_METALS),
    ("gümüş", ASSET_GROUP_PRECIOUS_METALS),
    ("gumus", ASSET_GROUP_PRECIOUS_METALS),
    ("hisse senet", ASSET_GROUP_EQUITY),
    ("borsa y.fon", ASSET_GROUP_FUND),
    ("borsa yatirim fonu", ASSET_GROUP_FUND),
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
    "3- fon",
    "4 - toplam",
    "4- fon toplam",
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



def _parse_kap_number(raw: Any) -> Optional[float]:
    """Parse KAP numeric cells in either TR or EN separator format."""
    text = str(raw or "").strip().replace(" ", "").replace("%", "")
    if not text or text in {":", "-", "—"}:
        return None

    if not re.fullmatch(r"-?[\d.,]+", text):
        return None

    if "," in text and "." in text:
        # Whichever separator appears last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text.replace(",", "")
    elif "," in text:
        # Existing KAP/TR convention: comma is decimal separator.
        normalized = text.replace(".", "").replace(",", ".")
    else:
        normalized = text

    try:
        return float(normalized)
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
    as_of: Optional[date] = None,
) -> KapPdrDiscovery:
    code = normalize_fund_code(fund_code)
    matches = [dict(row) for row in rows if _is_pdr_row(row, code)]
    if as_of is not None:
        from services.turkiye_fund_pdr_window import pdr_row_is_applicable

        matches = [row for row in matches if pdr_row_is_applicable(row, as_of)]
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


def is_valid_isin(token: Any) -> bool:
    """Reject header glue such as TOPLAMTOPLAM. Keep ISO-shaped official tokens."""
    text = str(token or "").strip().upper()
    if len(text) != 12 or not text[:2].isalpha() or not text[2:].isalnum():
        return False
    if not text[-1].isdigit():
        return False
    if any(bad in text for bad in ("TOPLAM", "MENKUL", "KIYMET", "GRUPTO")):
        return False
    return True


def _isin_tokens(text: str) -> list[str]:
    return [token for token in _ISIN_RE.findall(text) if is_valid_isin(token)]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _has_ftd_tail(line: str) -> bool:
    match = _FTD_TAIL_RE.search(_plain(line))
    if not match:
        return False
    values = [parse_tr_number(part) for part in match.groups()]
    return all(item is not None and abs(item) <= 100.5 for item in values)


def _is_header(line: str) -> bool:
    folded = _fold(line)
    return any(_fold(prefix) in folded[:48] for prefix in _HEADER_SKIP)


def _section_from_line(line: str) -> Optional[str]:
    folded = _fold(line)

    # A named holding row with an explicit portfolio-% tail is data, not a
    # section header. This must run before asset-group normalization because
    # security/issuer names such as ALTNY / ALTINAY may contain words that
    # otherwise look like asset-class labels.
    plain = _plain(line)
    if re.match(
        r"^[A-Z][A-Z0-9]{2,5}\s+.+?\s+"
        r"-?\d{1,3}(?:\.\d{3})*,\d{2}\s+"
        r"-?\d{1,3}(?:\.\d{3})*,\d{2}\s+"
        r"-?\d+(?:,\d+)?%\s*$",
        plain,
    ):
        return None

    # KAP compact equity section markers.
    # Examples seen in official PDR tables: "A.PAY", "A) PAY".
    compact = re.sub(r"\s+", " ", str(line or "").strip())
    if re.match(r"(?i)^A\s*[.)-]\s*PAY\s*$", compact):
        return "HİSSE SENETLERİ"
    if "grup toplam" in folded or ("fon portfoy degeri" in folded and "tablosu" not in folded):
        return None
    if _is_header(line) and "kira" not in folded and "katilim" not in folded and "taahhut" not in folded:
        return None
    group = normalize_pdr_asset_group(line)
    if group == ASSET_GROUP_UNKNOWN:
        if (
            re.match(r"^[A-ZÇĞİÖŞÜI]\)\s+\S", line.strip(), flags=re.I)
            and not _has_numbered_tail(line)
            and not _isin_tokens(line)
            and not _BIST_CODE_RE.search(line)
        ):
            return re.sub(r"^#+\s*", "", line.strip())
        return None
    if len(_plain(line)) > 80 and _isin_tokens(line):
        return None
    return re.sub(r"^#+\s*", "", line.strip())


def _numbers(text: str) -> list[str]:
    return _NUM_TOKEN.findall(text)


def _numbers_without_isins(text: str) -> list[str]:
    cleaned = str(text or "")
    for isin in _isin_tokens(cleaned):
        cleaned = cleaned.replace(isin, " ")
    return _numbers(cleaned)


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
    name_blob = _fold(f"{security_name_raw or ''} {issuer_raw or ''} {asset_group_raw or ''}")
    if str(isin or "").startswith("TRXDRP") or "altin hazine" in name_blob:
        group = ASSET_GROUP_PRECIOUS_METALS
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
    text = _plain(line)
    isins = _isin_tokens(text)
    if not isins:
        return None
    isin = isins[0]
    ccy = None
    ccy_match = re.search(r"\b(TL|TRY|USD|EUR|AU1)\b", line)
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
    if not issuer:
        head = text.split(isin)[0] if isin else ""
        if "HAZİNE" in head:
            issuer = "HAZİNE"
        else:
            tail = re.search(rf"^(?P<head>.+?)\s+{re.escape(isin)}\s*$", line)
            if tail:
                issuer = _plain(re.sub(r"[\d.,:\-|]+", " ", tail.group("head")))
                issuer = re.sub(r"\s+", " ", issuer).strip() or None
                if issuer and not name:
                    name = issuer
            elif _plain(head):
                issuer = _plain(re.sub(r"\b(TL|TRY|USD|EUR|AU1)\b", " ", head)) or None
    # Prefer explicit KAP Grup% / Toplam% columns when present.
    # The final marked percentage is the FTD/Toplam% portfolio weight.
    explicit_pct_tokens = re.findall(
        r"(-?\d+(?:[.,]\d+)?)\s*%",
        text,
    )
    explicit_pcts = [
        parse_tr_number(token.replace(".", ","))
        for token in explicit_pct_tokens
    ]
    explicit_pcts = [item for item in explicit_pcts if item is not None]
    # Some KAP PDR layouts expose only one explicit percentage column.
    # When '%' is explicitly printed, that value is the portfolio weight.
    explicit_portfolio_weight = (
        explicit_pcts[-1] if explicit_pcts else None
    )

    # Prefer the structural KAP market-value + GRUP/FPD/FTD columns.
    # Wrapped identity/name text may follow the official financial columns;
    # numbers in that text (for example "KATILIM 30") must not leak into
    # market value or portfolio weight.
    isin_tail = text.split(isin, 1)[1] if isin in text else text
    ftd_row_match = _FTD_ROW_RE.search(isin_tail)

    financial_text = (
        isin_tail[:ftd_row_match.end()]
        if ftd_row_match is not None
        else isin_tail
    )
    nums = _numbers_without_isins(financial_text)

    weight = None
    market_value = None
    nominal = None
    unit_price = None

    if ftd_row_match is not None:
        grup = parse_tr_number(ftd_row_match.group("grup"))
        fpd = parse_tr_number(ftd_row_match.group("fpd"))
        ftd = parse_tr_number(ftd_row_match.group("ftd"))

        if all(
            item is not None and abs(item) <= 100.5
            for item in (grup, fpd, ftd)
        ):
            market_value = parse_tr_number(ftd_row_match.group("mv"))
            weight = ftd

    if len(nums) >= 4:
        parsed = [parse_tr_number(tok) for tok in nums]
        values = [item for item in parsed if item is not None]
        pcts = [item for item in values if abs(item) <= 100]

        if weight is None:
            if len(values) >= 3 and all(abs(item) <= 100 for item in values[-3:]):
                weight = values[-1]
                market_value = next(
                    (item for item in reversed(values[:-3]) if abs(item) >= 1),
                    None,
                )
            elif pcts:
                weight = pcts[-1]
                market_value = next(
                    (item for item in reversed(values) if abs(item) > 100),
                    None,
                )

        if len(values) >= 6:
            candidates = [item for item in values if item >= 100]
            if candidates:
                nominal = candidates[0]
            prices = [item for item in values if 1 < item < 200]
            if prices:
                unit_price = prices[0]

    if explicit_portfolio_weight is not None:
        weight = explicit_portfolio_weight

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
    if _isin_tokens(line) or "GRUP TOPLAMI" in line.upper():
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


def _numbered_weight(match: re.Match[str]) -> Optional[float]:
    value = parse_tr_number(match.group("w"))
    if value is None:
        return None
    if match.groupdict().get("wsign") == "-":
        return -abs(value)
    return value


def _is_numbered_ftd_summary(text: str) -> bool:
    folded = _fold(text)
    if folded.startswith("toplam"):
        return True
    if re.match(r"^[a-e][.)]\s*", folded) and any(
        token in folded
        for token in (
            "fon portfoy degeri",
            "hazir degerler",
            "alacaklar",
            "diger varliklar",
            "borclar",
        )
    ):
        return True
    return False


def _has_numbered_tail(line: str) -> bool:
    return bool(_NUMBERED_TAIL_RE.search(_plain(line)))


def _is_numbered_holding_start(line: str) -> bool:
    text = _plain(line)
    if not text or _is_header(text) or _is_page_noise(text) or _is_numbered_ftd_summary(text):
        return False
    if not _has_numbered_tail(text):
        return False
    if _has_ftd_tail(text) or _BIST_CODE_RE.search(text):
        return False
    if is_valid_isin(text.split()[0].rstrip(".,;:")):
        return False
    return True


def _parse_numbered_holding_row(
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
    """ELZ-style numbered PDR rows: CODE NAME nominal market_value %weight."""
    text = _plain(line)
    if not text or _is_header(text) or _is_numbered_ftd_summary(text):
        return None
    if _has_ftd_tail(text) or _BIST_CODE_RE.search(text):
        return None
    match = _NUMBERED_HOLDING_RE.match(text) or _NUMBERED_NAMED_RE.match(text)
    if not match:
        return None
    weight = _numbered_weight(match)
    if weight is None:
        return None
    groups = match.groupdict()
    code = str(groups.get("code") or "").strip() or None
    name = str(groups.get("name") or "").strip() or code
    if code is None and name:
        first = name.split()[0]
        if re.fullmatch(r"[A-Z]{2,6}(?:\.[A-Za-z0-9ÇçĞğİıÖöŞşÜü.%/-]+)+", first) or re.fullmatch(
            r"[A-Z]{3,6}(?:[A-Z0-9]{1,2})?", first
        ):
            code = first
            name = name[len(first) :].strip() or first
    isins = _isin_tokens(text)
    isin = isins[0] if isins else None
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=name,
        issuer_raw=name if not code else None,
        isin=isin,
        official_code=code or isin,
        maturity_date=parse_tr_date(text),
        currency="TRY" if re.search(r"\b(TL|TRY)\b", text) else None,
        quantity=None,
        nominal=parse_tr_number(match.group("nom")),
        unit_price=None,
        market_value=parse_tr_number(match.group("mv")),
        portfolio_weight=weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )



def _parse_ocr_equity_row(
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
    """Fail-closed recovery for KAP equity rows with OCR-damaged identities."""

    text = _plain(line)
    code = _ocr_equity_code(text, section)
    if not code or _is_header(text) or "GRUP TOPLAMI" in text.upper():
        return None

    pct_tokens = re.findall(r"(-?\d+(?:[.,]\d+)?)\s*%", text)
    pct_values = [
        parse_tr_number(token.replace(".", ","))
        for token in pct_tokens
    ]
    pct_values = [value for value in pct_values if value is not None]

    if len(pct_values) < 2:
        return None

    # KAP's final explicit percentage column is Toplam%.
    weight = pct_values[-1]

    # OCR fallback establishes the explicit Toplam% weight only.
    # Do not infer market value from ambiguous numeric column positions.
    market_value = None

    # Preserve only identities that KAP actually supplied.
    # A malformed OCR ISIN is deliberately NOT promoted to canonical ISIN.
    valid_isins = _isin_tokens(text)
    isin = valid_isins[0] if valid_isins else None

    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=code,
        issuer_raw=None,
        isin=isin,
        official_code=isin,
        maturity_date=parse_tr_date(text),
        currency=None,
        quantity=None,
        nominal=None,
        unit_price=None,
        market_value=market_value,
        portfolio_weight=weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


_PERCENT_TAIL_TICKER_RE = re.compile(
    r"^(?P<code>[A-Z][A-Z0-9]{2,5})\s+"
    r"(?P<name>.+?)\s+"
    r"(?P<nominal>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2}))\s+"
    r"(?P<market_value>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2}))\s+"
    r"(?P<weight>-?\d+(?:[.,]\d+)?)%"
    r"(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü.]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü.]+)*)?\s*$"
)


def _buffer_has_completed_percent_tail(line: str) -> bool:
    """True when a buffer starts with a complete explicit-% holding row.

    PDF name continuations such as "A.Ş." may already have been appended
    after the completed holding. Only the leading completed row matters
    when deciding whether a following holding must start a new chunk.
    """
    text = _plain(line)
    if not text:
        return False

    match = re.match(
        r"^[A-Z][A-Z0-9]{2,5}\s+.+?\s+"
        r"-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2})\s+"
        r"-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2})\s+"
        r"-?\d+(?:[.,]\d+)?%",
        text,
    )
    return match is not None


def _percent_tail_ticker_match(line: str) -> Optional[re.Match[str]]:
    """Match named KAP rows ending nominal / market value / explicit %."""
    text = _plain(line)
    if not text or _isin_tokens(text):
        return None
    if "GRUP TOPLAMI" in text.upper() or _is_header(text):
        return None
    return _PERCENT_TAIL_TICKER_RE.match(text)


def _parse_percent_tail_ticker_row(
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
    """Parse named holdings without ISIN/currency when KAP gives explicit %."""
    if not section:
        return None

    group = normalize_pdr_asset_group(section)
    if group == ASSET_GROUP_UNKNOWN:
        return None

    match = _percent_tail_ticker_match(line)
    if not match:
        return None

    nominal = _parse_kap_number(match.group("nominal"))
    market_value = _parse_kap_number(match.group("market_value"))
    weight = _parse_kap_number(match.group("weight"))

    if nominal is None or market_value is None or weight is None:
        return None
    if weight < 0 or weight > 100.5:
        return None

    code = match.group("code")

    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=code,
        issuer_raw=_plain(match.group("name")) or None,
        isin=None,
        official_code=code,
        maturity_date=None,
        currency=None,
        quantity=None,
        nominal=nominal,
        unit_price=None,
        market_value=market_value,
        portfolio_weight=weight,
        fund_total_value=fund_total_value,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    )


def _parse_ticker_row(
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
    """Named/ticker rows where ISIN is wrapped onto a later official line."""
    text = _plain(line)
    match = _TICKER_ROW_RE.search(text)
    if not match or not _has_ftd_tail(text):
        return None
    if "GRUP TOPLAMI" in text.upper() or _is_header(text):
        return None
    ticker = match.group(1)
    ccy = match.group(2)
    isins = _isin_tokens(text)
    nums = [parse_tr_number(tok) for tok in _numbers_without_isins(text)]
    values = [item for item in nums if item is not None]
    weight = values[-1] if len(values) >= 3 and all(abs(item) <= 100.5 for item in values[-3:]) else None
    market_value = next((item for item in reversed(values[:-3]) if item is not None and abs(item) >= 1), None)
    issuer = None
    if "HAZİNE" in text:
        issuer = "HAZİNE"
    else:
        head = re.split(r"\b(?:TL|TRY|USD|EUR|AU1)\b", text, maxsplit=1)
        if len(head) > 1:
            rest = re.split(r"\d", head[1], maxsplit=1)[0]
            issuer = _plain(rest) or None
    return _holding(
        fund_code=fund_code,
        report_period=report_period,
        report_date=report_date,
        asset_group_raw=section,
        security_name_raw=ticker,
        issuer_raw=issuer,
        isin=isins[0] if isins else None,
        official_code=isins[0] if isins else ticker,
        maturity_date=parse_tr_date(text),
        currency=ccy,
        quantity=None,
        nominal=next((item for item in values if item is not None and abs(item) >= 100), None),
        unit_price=None,
        market_value=market_value,
        portfolio_weight=weight,
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
    found = _isin_tokens(text)
    if found:
        isin = found[0]
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
        (r"B[.\-)]+\s*HAZIR DE[ĞG]ERLER\s+(-?[\d.]+,\d+)\s+(-?%-?[\d,]+)", "HAZIR DEĞERLER"),
        (r"C[.\-)]+\s*ALACAKLAR\s+(-?[\d.]+,\d+)\s+(-?%-?[\d,]+)", "ALACAKLAR"),
        (r"E[.\-)]+\s*BOR[ÇC]LAR\s+(-?[\d.]+,\d+)\s+(-?%-?[\d,]+)", "BORÇLAR"),
    )
    seen: set[str] = set()
    for pattern, label in patterns:
        if label in seen:
            continue
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        seen.add(label)
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


def _is_page_noise(line: str) -> bool:
    if _isin_tokens(line) or _BIST_CODE_RE.search(line):
        return False
    folded = _fold(line)
    if _PAGE_NOISE_RE.search(folded):
        return True
    if "ihracci kurum" in folded and "isin kodu" in folded:
        return True
    if "menkul kiymet" in folded and "cinsi" in folded:
        return True
    return False


def _is_holding_row_start(line: str) -> bool:
    text = _plain(line)
    if not text or "GRUP TOPLAMI" in text.upper() or _is_header(text) or _is_page_noise(text):
        return False
    first = text.split()[0].rstrip(".,;:")
    if is_valid_isin(first):
        return True
    if _percent_tail_ticker_match(text):
        return True
    if _TICKER_ROW_RE.match(text) and re.search(r"\b(TL|TRY|USD|EUR|AU1)\b", text):
        return True
    if re.match(r"^(ALTIN|G[UÜ]M[UÜ][SŞ])\b", text, flags=re.I) and re.search(r"\b(TL|TRY|AU1)\b", text):
        return True
    if _has_ftd_tail(text) and re.search(r"\b(TL|TRY)\b", text) and not _isin_tokens(text):
        return True
    if _is_numbered_holding_start(text):
        return True
    return False


def _is_trailing_identity_wrap(line: str) -> bool:
    """Identity fields printed on the next line after a complete FTD weight row."""
    text = _plain(line)
    if not text or _has_ftd_tail(text) or _BIST_CODE_RE.search(text):
        return False
    if "GRUP TOPLAMI" in text.upper() or _is_header(text):
        return False
    if _TICKER_ROW_RE.match(text) or _is_holding_row_start(text):
        return False
    money = [parse_tr_number(tok) for tok in _numbers(text) if "," in tok]
    if any(item is not None and abs(item) > 100 for item in money):
        return False
    if _isin_tokens(text):
        return True
    folded = _fold(text)
    return any(token in folded for token in ("portfoy", "yonetimi", "a.s.", "varlik kiralama", "finans"))


def _is_wrap_continuation(line: str, buf: str) -> bool:
    """Issuer/ISIN wrapped onto the next PDF line of the same official row."""

    text = _plain(line)
    prior = _plain(buf)

    if not text or not prior:
        return False

    if "GRUP TOPLAMI" in text.upper() or _is_header(text) or _is_page_noise(text):
        return False

    if _has_ftd_tail(text):
        return False

    if _is_numbered_holding_start(text):
        return False

    if _BIST_CODE_RE.search(text):
        return False

    first = text.split()[0].rstrip(".,;:")

    if is_valid_isin(first) and (_has_ftd_tail(text) or len(_numbers(text)) >= 4):
        return False

    if (
        _TICKER_ROW_RE.match(text)
        and re.search(r"\b(TL|TRY|USD|EUR|AU1)\b", text)
        and len(_numbers(text)) >= 3
    ):
        return False

    money = [parse_tr_number(tok) for tok in _numbers(text) if "," in tok]

    if any(item is not None and abs(item) > 100 for item in money):
        return False

    prior_isins = _isin_tokens(prior)
    line_isins = _isin_tokens(text)

    if prior_isins and line_isins and line_isins[0] not in prior_isins:
        return False

    # Fail closed. Do not merge an otherwise-unclassified PDF line merely
    # because no negative rule matched it.
    if prior_isins and line_isins and line_isins[0] in prior_isins:
        return True

    if prior_isins and not line_isins:
        folded = _fold(text)
        if any(
            token in folded
            for token in (
                "portfoy",
                "yonetimi",
                "a.s.",
                "varlik kiralama",
                "finans",
            )
        ):
            return True

    return False


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
        if not text or _is_page_noise(text):
            return
        parts = [part.strip() for part in _ISIN_HOLDING_SPLIT.split(text) if part.strip()]
        if not parts:
            parts = [text]
        for part in parts:
            if part.upper().startswith("GRUP TOPLAMI") or _is_page_noise(part):
                continue
            chunks.append((section, part))

    for raw in body.splitlines():
        line = raw.strip()
        if not line or line in {"|", ":"} or set(line) <= {"|", "-", " "}:
            continue
        if re.search(r"IV-?FON TOPLAM|4\s*-?\s*FON TOPLAM DE[ĞG]ER|4 - TOPLAM DE[ĞG]ER|VII-PORTF|7 - PORTF|8 - [İI]TFALAR|9 - PORTF", line, flags=re.I):
            flush()
            break
        if _is_page_noise(line):
            continue
        header = _section_from_line(line)
        if header and not _isin_tokens(line) and not _BIST_CODE_RE.search(line) and not _TICKER_ROW_RE.match(_plain(line)) and not _is_numbered_holding_start(line):
            flush()
            section = header
            continue
        if _is_numbered_holding_start(line):
            flush()
            buf = line
            continue
        if line.upper().lstrip().startswith("TOPLAM:") or re.match(r"^TOPLAM\s*$", line.strip(), flags=re.I):
            flush()
            continue
        if line.startswith("|") and not _BIST_CODE_RE.search(line):
            pipe_buf.append(line)
            continue
        if _BIST_CODE_RE.search(line) or _ocr_equity_code(line, section):
            flush()
            chunks.append((section, line))
            continue
        if "GRUP TOPLAMI" in line.upper() and not _isin_tokens(line):
            flush()
            continue
        if (
            buf
            and (_has_ftd_tail(buf) or _buffer_has_completed_percent_tail(buf))
            and _is_holding_row_start(line)
            and not _is_wrap_continuation(line, buf)
        ):
            flush()
            buf = line
            continue
        if _is_wrap_continuation(line, buf):
            buf = f"{buf} {line}".strip()
            continue
        if (
            not _isin_tokens(line)
            and re.search(r"\b(TL|TRY)\b", line)
            and _TR_DATE_RE.search(line)
            and _has_ftd_tail(line)
        ):
            buf = f"{buf} {line}".strip() if buf else line
            flush()
            continue
        if _isin_tokens(line) and buf and _isin_tokens(buf) and re.search(r"\b(TL|TRY|AU1)\b", buf):
            flush()
            buf = line
            continue
        buf = f"{buf} {line}".strip() if buf else line
    flush()
    return chunks


def _cut_holdings_body(text: str) -> str:
    """Return only the official portfolio-holdings table when boundaries exist.

    Prefer the Section III portfolio-value table over earlier monthly
    composition summaries.  Earlier summaries may contain asset-class names
    such as "Kira Sertifikaları" and must not leak section state into the
    actual security rows.
    """
    source = text

    # Stop before Section IV / fund-total summary.
    end_match = re.search(
        r"(?im)^\s*(?:IV|4)[.\-–—]?\s*FON\s+TOPLAM",
        source,
    )
    if end_match:
        source = source[:end_match.start()]

    # Prefer the real Section III holdings table whenever it is present.
    start_patterns = (
        r"(?im)^\s*III[.\-–—]?\s*FON\s+PORTF[ÖO]Y\s+(?:DE[ĞG]ER|cE[ĞG]ER)",
        r"(?im)^\s*3[.\-–—]?\s*FON\s+PORTF[ÖO]Y\s+(?:DE[ĞG]ER|cE[ĞG]ER)",
    )

    for pattern in start_patterns:
        match = re.search(pattern, source)
        if match:
            return source[match.start():]

    # Legacy/fallback layouts may omit an explicit Section III marker.
    # Keep the bounded text rather than inventing a start point.
    return source

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
    body = _GLUED_ISIN.sub(r" \1", str(text or ""))
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
        numbered = _parse_numbered_holding_row(
            line,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            section=section,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
        if numbered:
            holdings.append(numbered)
            continue
        ticker = _parse_ticker_row(
            line,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            section=section,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
        if ticker:
            holdings.append(ticker)
            continue

        percent_tail = _parse_percent_tail_ticker_row(
            line,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            section=section,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
        if percent_tail:
            holdings.append(percent_tail)
            continue

        # Conservative fallback for KAP equity rows whose ticker/ISIN text
        # layer is OCR-damaged. Normal canonical parsers always have priority.
        ocr_equity = _parse_ocr_equity_row(
            line,
            fund_code=code,
            report_period=report_period,
            report_date=report_date,
            section=section,
            fund_total_value=fund_total,
            source_notification_id=source_notification_id,
            source_attachment=source_attachment,
        )
        if ocr_equity:
            holdings.append(ocr_equity)
            continue

        if section and normalize_pdr_asset_group(section) in {
            ASSET_GROUP_PARTICIPATION_ACCOUNT,
            ASSET_GROUP_REPO,
        } and not _isin_tokens(line):
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
        if _isin_tokens(line):
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
    seen_overlay = {
        _fold(row.security_name_raw)
        for row in holdings
        if row.security_name_raw
    }
    for extra in _parse_ftd_overlay(
        body,
        fund_code=code,
        report_period=report_period,
        report_date=report_date,
        fund_total_value=fund_total,
        source_notification_id=source_notification_id,
        source_attachment=source_attachment,
    ):
        if _fold(extra.security_name_raw) in seen_overlay:
            continue
        holdings.append(extra)
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
        # Equity rows that look like BIST securities but have no canonical
        # identity may be OCR-damaged evidence. Keep their raw name for audit,
        # but do not promote it back into a canonical ticker.
        raw_name = _plain(row.security_name_raw or "")
        raw_equity_code = (
            row.asset_group == ASSET_GROUP_EQUITY
            and _OCR_EQUITY_CODE_RE.fullmatch(raw_name) is not None
        )
        canonical_identity_missing = not row.official_code and not row.isin
        ticker = (
            ""
            if canonical_identity_missing and raw_equity_code
            else row.official_code or row.isin or row.issuer_raw or row.security_name_raw or ""
        )

        mapped.append(
            OfficialHolding(
                fund_symbol=file.fund_code,
                as_of=as_of,
                ticker=ticker,
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
                    "issuer_columns": {"issuer": row.issuer_raw} if row.issuer_raw else {},
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


def issuer_weight_map(file: KapPdrHoldingsFile) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for row in file.holdings:
        if row.portfolio_weight is None or not row.issuer_raw:
            continue
        name = str(row.issuer_raw).strip()
        buckets[name] = buckets.get(name, 0.0) + float(row.portfolio_weight)
    return {name: round(weight, 4) for name, weight in buckets.items()}


def issuer_concentration_stats(file: KapPdrHoldingsFile) -> tuple[Optional[float], Optional[float], int]:
    weights = sorted(issuer_weight_map(file).values(), reverse=True)
    if not weights:
        return None, None, 0
    largest = weights[0]
    top10 = round(sum(weights[:10]), 4)
    return largest, top10, len(weights)


def weighted_average_maturity_days(
    file: KapPdrHoldingsFile,
    *,
    as_of: Optional[date] = None,
) -> Optional[float]:
    if as_of is None:
        if file.report_date:
            try:
                as_of = date.fromisoformat(file.report_date[:10])
            except ValueError:
                as_of = None
        if as_of is None and file.report_period:
            try:
                as_of = date.fromisoformat(file.report_period + "-01")
            except ValueError:
                as_of = None
    if as_of is None:
        return None
    total_w = 0.0
    weighted = 0.0
    for row in file.holdings:
        if row.portfolio_weight is None or not row.maturity_date:
            continue
        try:
            maturity = date.fromisoformat(row.maturity_date[:10])
        except ValueError:
            continue
        total_w += float(row.portfolio_weight)
        weighted += float(row.portfolio_weight) * float((maturity - as_of).days)
    if total_w <= 0:
        return None
    return round(weighted / total_w, 4)
