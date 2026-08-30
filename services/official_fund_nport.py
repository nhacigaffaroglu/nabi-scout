"""Pilot SEC EDGAR N-PORT identity and period parsing.

No crawler. Unknown series/class fail closed. Daily NAV is never inferred
from a single period snapshot.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Optional
from services.fund_product_contract import (
    FundFixedIncomeRiskEvidence,
    NportDebtHolding,
    NportTenorRisk,
    OfficialNportSnapshot,
    PILOT_FUND_SYMBOLS,
)

NPORT_SOURCE = "sec_edgar_nport"


@dataclass(frozen=True)
class OfficialNportIdentity:
    symbol: str
    cik: str
    series_id: str
    class_id: str
    registrant: str
    file_number: str


PILOT_NPORT_IDENTITIES = {
    "SPUS": OfficialNportIdentity(
        symbol="SPUS",
        cik="0001742912",
        series_id="S000067283",
        class_id="C000216395",
        registrant="Tidal Trust I",
        file_number="811-23377",
    ),
    "SPSK": OfficialNportIdentity(
        symbol="SPSK",
        cik="0001742912",
        series_id="S000067282",
        class_id="C000216394",
        registrant="Tidal Trust I",
        file_number="811-23377",
    ),
    "SPRE": OfficialNportIdentity(
        symbol="SPRE",
        cik="0001742912",
        series_id="S000070461",
        class_id="C000223966",
        registrant="Tidal Trust I",
        file_number="811-23377",
    ),
    "SPWO": OfficialNportIdentity(
        symbol="SPWO",
        cik="0001989916",
        series_id="S000083496",
        class_id="C000247153",
        registrant="SP Funds Trust",
        file_number="811-23893",
    ),
}


def nport_identity(symbol: str) -> Optional[OfficialNportIdentity]:
    fund = str(symbol or "").strip().upper()
    if fund not in PILOT_FUND_SYMBOLS:
        return None
    return PILOT_NPORT_IDENTITIES.get(fund)


def nport_source_url(*, cik: str, accession: str) -> str:
    cik_n = str(cik or "").strip().lstrip("0") or "0"
    acc_n = str(accession or "").replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_n}/{acc_n}/primary_doc.xml"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _first_text(root: ET.Element, names: tuple[str, ...]) -> Optional[str]:
    wanted = {name.lower() for name in names}
    for node in root.iter():
        if _local(node.tag).lower() in wanted and node.text and node.text.strip():
            return node.text.strip()
    return None


def _parse_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_official_nport_xml(
    xml_text: str,
    *,
    symbol: str,
    accession: str = "",
) -> Optional[OfficialNportSnapshot]:
    """Parse one N-PORT document for a known pilot fund. Identity must match."""
    expected = nport_identity(symbol)
    if expected is None:
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    series = (_first_text(root, ("seriesId", "seriesid")) or "").upper()
    class_id = (_first_text(root, ("classId", "classid")) or "").upper()
    cik = (_first_text(root, ("cik",)) or "").zfill(10)
    if series != expected.series_id or class_id != expected.class_id:
        return None
    if cik and cik != expected.cik:
        return None
    tot_assets = _parse_number(_first_text(root, ("totAssets", "totalAssets")))
    net_assets = _parse_number(_first_text(root, ("netAssets",)))
    shares = _parse_number(
        _first_text(root, ("unitsOutstanding", "shrOutstanding", "sharesOutstanding"))
    )
    period = _first_text(root, ("repPdEnded", "periodOfReport", "rptPdEnded"))
    nav = None
    nav_method = ""
    limitations: list[str] = []
    if net_assets is not None and shares is not None and shares > 0:
        nav = round(net_assets / shares, 4)
        nav_method = "NET_ASSETS_DIV_UNITS_OUTSTANDING"
    else:
        limitations.append("NPORT_NAV_NOT_DIRECTLY_REPORTED")
    limitations.append("NPORT_NOT_DAILY_NAV_SERIES")
    acc = accession or _first_text(root, ("accessionNumber", "accession")) or ""
    return OfficialNportSnapshot(
        symbol=expected.symbol,
        cik=expected.cik,
        series_id=expected.series_id,
        class_id=expected.class_id,
        registrant=expected.registrant,
        period_of_report=period,
        accession=acc,
        source_url=nport_source_url(cik=expected.cik, accession=acc),
        tot_assets=tot_assets,
        net_assets=net_assets,
        shares_outstanding=shares,
        nav_per_share=nav,
        nav_method=nav_method,
        limitations=tuple(limitations),
    )


NPORT_TENOR_ATTRS = (
    ("period3Mon", "3m"),
    ("period1Yr", "1y"),
    ("period5Yr", "5y"),
    ("period10Yr", "10y"),
    ("period30Yr", "30y"),
)
UNKNOWN_ISSUER_TOKENS = frozenset({"", "N/A", "NA", "NONE", "NULL"})
UNKNOWN_LEI_TOKENS = frozenset({"", "N/A", "NA", "00000000000000000000"})


def _first_element(root: ET.Element, names: tuple[str, ...]) -> Optional[ET.Element]:
    wanted = {name.lower() for name in names}
    for node in root.iter():
        if _local(node.tag).lower() in wanted:
            return node
    return None


def _child_text(node: ET.Element, names: tuple[str, ...]) -> Optional[str]:
    wanted = {name.lower() for name in names}
    for child in list(node) + [node]:
        if _local(child.tag).lower() in wanted and child.text and child.text.strip():
            return child.text.strip()
    return None


def _attr_or_text(node: Optional[ET.Element], attr: str = "value") -> Optional[str]:
    if node is None:
        return None
    raw = node.get(attr) or (node.text or "").strip()
    return raw.strip() if raw and raw.strip() else None


def _tenor_risks(node: Optional[ET.Element]) -> tuple[NportTenorRisk, ...]:
    if node is None:
        return ()
    rows: list[NportTenorRisk] = []
    for attr, label in NPORT_TENOR_ATTRS:
        value = _parse_number(node.get(attr))
        if value is None:
            continue
        rows.append(NportTenorRisk(period=label, value=value))
    return tuple(rows)


def _official_issuer_name(raw: Optional[str]) -> Optional[str]:
    text = " ".join(str(raw or "").split())
    if text.upper() in UNKNOWN_ISSUER_TOKENS:
        return None
    return text or None


def _official_lei(raw: Optional[str]) -> Optional[str]:
    text = str(raw or "").strip().upper()
    if text in UNKNOWN_LEI_TOKENS:
        return None
    return text or None


def _issuer_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def parse_official_nport_fixed_income(
    xml_text: str,
    *,
    symbol: str,
    accession: str = "",
) -> Optional[FundFixedIncomeRiskEvidence]:
    """Parse official N-PORT rate, spread, issuer, and maturity fields.

    Does not treat DV01/DV100 as duration. Does not invent credit ratings.
    Groups issuers only by the official N-PORT name field.
    """
    expected = nport_identity(symbol)
    if expected is None:
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    series = (_first_text(root, ("seriesId", "seriesid")) or "").upper()
    class_id = (_first_text(root, ("classId", "classid")) or "").upper()
    if series != expected.series_id or class_id != expected.class_id:
        return None
    as_of = _first_text(root, ("repPdDate", "rptPdDate"))
    period_ended = _first_text(root, ("repPdEnd", "repPdEnded", "periodOfReport"))
    dv01 = _tenor_risks(_first_element(root, ("intrstRtRiskdv01", "interestRateRiskDv01")))
    dv100 = _tenor_risks(_first_element(root, ("intrstRtRiskdv100", "interestRateRiskDv100")))
    ig = _tenor_risks(_first_element(root, ("creditSprdRiskInvstGrade",)))
    non_ig = _tenor_risks(_first_element(root, ("creditSprdRiskNonInvstGrade",)))
    holdings: list[NportDebtHolding] = []
    for node in root.iter():
        if _local(node.tag).lower() != "invstorsec":
            continue
        issuer = _official_issuer_name(_child_text(node, ("name",)))
        isin_node = None
        cusip_node = None
        lei_node = None
        title_node = None
        maturity_node = None
        pct_node = None
        val_node = None
        cur_node = None
        issuer_cat_node = None
        asset_cat_node = None
        for child in node.iter():
            local = _local(child.tag).lower()
            if local == "isin" and isin_node is None:
                isin_node = child
            elif local == "cusip" and cusip_node is None:
                cusip_node = child
            elif local == "lei" and lei_node is None:
                lei_node = child
            elif local == "title" and title_node is None:
                title_node = child
            elif local == "maturitydt" and maturity_node is None:
                maturity_node = child
            elif local == "pctval" and pct_node is None:
                pct_node = child
            elif local == "valusd" and val_node is None:
                val_node = child
            elif local == "curcd" and cur_node is None:
                cur_node = child
            elif local == "issuercat" and issuer_cat_node is None:
                issuer_cat_node = child
            elif local == "assetcat" and asset_cat_node is None:
                asset_cat_node = child
        weight = _parse_number(_attr_or_text(pct_node) or (pct_node.text if pct_node is not None else None)) or 0.0
        holdings.append(
            NportDebtHolding(
                issuer_name=issuer or "",
                lei=_official_lei(_attr_or_text(lei_node) or (lei_node.text if lei_node is not None else None)),
                title=(_attr_or_text(title_node) or (title_node.text if title_node is not None else None) or "").strip(),
                cusip=_official_issuer_name(_attr_or_text(cusip_node) or (cusip_node.text if cusip_node is not None else None)),
                isin=_official_issuer_name(_attr_or_text(isin_node) or (isin_node.text if isin_node is not None else None)),
                maturity_date=_attr_or_text(maturity_node) or (maturity_node.text.strip() if maturity_node is not None and maturity_node.text else None),
                weight_pct=weight,
                value_usd=_parse_number(_attr_or_text(val_node) or (val_node.text if val_node is not None else None)),
                currency=_attr_or_text(cur_node) or (cur_node.text.strip() if cur_node is not None and cur_node.text else None),
                issuer_category=_attr_or_text(issuer_cat_node) or (issuer_cat_node.text.strip() if issuer_cat_node is not None and issuer_cat_node.text else None),
                asset_category=_attr_or_text(asset_cat_node) or (asset_cat_node.text.strip() if asset_cat_node is not None and asset_cat_node.text else None),
            )
        )
    dated_w = 0.0
    unknown_mat_w = 0.0
    unknown_issuer_w = 0.0
    wam_num = 0.0
    as_of_date = None
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            as_of_date = None
    issuer_weights: dict[str, float] = {}
    currency_weights: dict[str, float] = {}
    official_names = 0
    for row in holdings:
        issuer = _official_issuer_name(row.issuer_name)
        if issuer is None:
            unknown_issuer_w += row.weight_pct
        else:
            official_names += 1
            issuer_weights[_issuer_key(issuer)] = issuer_weights.get(_issuer_key(issuer), 0.0) + row.weight_pct
        if row.currency:
            currency_weights[row.currency] = currency_weights.get(row.currency, 0.0) + row.weight_pct
        if row.maturity_date and as_of_date is not None:
            try:
                maturity = date.fromisoformat(row.maturity_date)
            except ValueError:
                unknown_mat_w += row.weight_pct
                continue
            years = (maturity - as_of_date).days / 365.25
            dated_w += row.weight_pct
            wam_num += years * row.weight_pct
        else:
            unknown_mat_w += row.weight_pct
    raw_sum = round(sum(item.weight_pct for item in holdings), 6)
    residual = round(max(0.0, 100.0 - raw_sum), 4)
    ranked = sorted(issuer_weights.values(), reverse=True)
    largest = round(ranked[0], 4) if ranked else None
    top10 = round(sum(ranked[:10]), 4) if ranked else None
    wam = round(wam_num / dated_w, 4) if dated_w > 0 else None
    limitations = [
        "DV01_IS_NOT_DURATION",
        "CREDIT_SPREAD_IS_NOT_RATING",
        "WAM_EXCLUDES_RESIDUAL_AND_UNDATED",
        "NPORT_NOT_DAILY_NAV_SERIES",
    ]
    if not dv01 and not dv100:
        limitations.append("INTEREST_RATE_RISK_MISSING")
    if official_names == 0:
        limitations.append("OFFICIAL_ISSUER_NAME_MISSING")
    acc = accession or _first_text(root, ("accessionNumber", "accession")) or ""
    reliability = "official_nport" if (dv01 or dv100 or official_names) else "missing"
    return FundFixedIncomeRiskEvidence(
        fund_symbol=expected.symbol,
        as_of=as_of,
        period_ended=period_ended,
        interest_rate_risk_dv01=dv01,
        interest_rate_risk_dv100=dv100,
        credit_spread_risk_ig=ig,
        credit_spread_risk_non_ig=non_ig,
        holdings=tuple(holdings),
        holding_count=len(holdings),
        dated_weight_pct=round(dated_w, 4),
        residual_weight_pct=residual,
        unknown_maturity_weight_pct=round(unknown_mat_w, 4),
        weighted_average_maturity_years=wam,
        duration=None,
        credit_quality=None,
        official_issuer_field="nport_name",
        official_issuer_field_present=official_names > 0,
        unknown_issuer_weight_pct=round(unknown_issuer_w, 4),
        largest_issuer_weight=largest,
        top10_issuer_weight=top10,
        issuer_count=len(issuer_weights),
        currency_weights=tuple(sorted(currency_weights.items(), key=lambda item: item[1], reverse=True)),
        source=NPORT_SOURCE,
        source_url=nport_source_url(cik=expected.cik, accession=acc),
        provenance=(NPORT_SOURCE, "official_nport_fixed_income"),
        reliability=reliability,
        limitations=tuple(limitations),
    )
