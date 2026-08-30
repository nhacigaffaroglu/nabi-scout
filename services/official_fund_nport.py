"""Pilot SEC EDGAR N-PORT identity and period parsing.

No crawler. Unknown series/class fail closed. Daily NAV is never inferred
from a single period snapshot.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from services.fund_product_contract import OfficialNportSnapshot, PILOT_FUND_SYMBOLS

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
