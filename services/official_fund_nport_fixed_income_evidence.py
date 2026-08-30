"""Captured official SPSK N-PORT fixed-income evidence.

Uses the canonical N-PORT parser. No second holdings model and no name guessing.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from services.official_fund_nport import (
    parse_official_nport_fixed_income,
    parse_official_nport_xml,
)

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_nport_evidence"
SPSK_HOLDINGS_TSV = EVIDENCE_DIR / "SPSK_nport_holdings.tsv"
SPSK_FUNDINFO_XML = EVIDENCE_DIR / "SPSK_nport_fundinfo.xml"
SPSK_ACCESSION = "0002000324-26-003239"
SPSK_AS_OF = "2026-05-31"
SPSK_PERIOD_END = "2026-11-30"


def _xml_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA"}:
        return "N/A"
    return escape(text)


def build_spsk_nport_fixed_income_xml() -> str:
    rows = SPSK_HOLDINGS_TSV.read_text(encoding="utf-8").splitlines()
    holdings: list[str] = []
    for line in rows:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        name, lei, title, cusip, isin, maturity, pct, val, cur, issuer_cat, asset_cat, country = parts[:12]
        holdings.append(
            "    <invstOrSec>\n"
            f"      <name>{_xml_text(name)}</name>\n"
            f"      <lei>{_xml_text(lei)}</lei>\n"
            f"      <title>{_xml_text(title)}</title>\n"
            f"      <cusip>{_xml_text(cusip)}</cusip>\n"
            f"      <identifiers><isin value=\"{_xml_text(isin)}\"/></identifiers>\n"
            f"      <pctVal>{escape(pct)}</pctVal>\n"
            f"      <valUSD>{escape(val)}</valUSD>\n"
            f"      <curCd>{_xml_text(cur)}</curCd>\n"
            f"      <issuerCat>{_xml_text(issuer_cat)}</issuerCat>\n"
            f"      <assetCat>{_xml_text(asset_cat)}</assetCat>\n"
            f"      <invCountry>{_xml_text(country)}</invCountry>\n"
            f"      <debtSec><maturityDt>{escape(maturity)}</maturityDt></debtSec>\n"
            "    </invstOrSec>"
        )
    fundinfo = SPSK_FUNDINFO_XML.read_text(encoding="utf-8")
    start = fundinfo.find("<fundInfo")
    end = fundinfo.rfind("</fundInfo>") + len("</fundInfo>")
    fund_block = fundinfo[start:end] if start >= 0 and end > start else "<fundInfo/>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">\n'
        "  <headerData>\n"
        "    <submissionType>NPORT-P</submissionType>\n"
        f"    <accessionNumber>{SPSK_ACCESSION}</accessionNumber>\n"
        "    <filerInfo><filer><issuerCredentials><cik>0001742912</cik></issuerCredentials></filer></filerInfo>\n"
        "  </headerData>\n"
        "  <genInfo>\n"
        "    <regName>Tidal Trust I</regName>\n"
        "    <seriesId>S000067282</seriesId>\n"
        "    <seriesName>SP Funds Dow Jones Global Sukuk ETF</seriesName>\n"
        "    <classId>C000216394</classId>\n"
        f"    <repPdEnd>{SPSK_PERIOD_END}</repPdEnd>\n"
        f"    <repPdDate>{SPSK_AS_OF}</repPdDate>\n"
        "  </genInfo>\n"
        f"  {fund_block}\n"
        "  <invstOrSecs>\n"
        + "\n".join(holdings)
        + "\n  </invstOrSecs>\n"
        "</edgarSubmission>\n"
    )


def load_spsk_nport_fixed_income():
    xml_text = build_spsk_nport_fixed_income_xml()
    return parse_official_nport_fixed_income(
        xml_text,
        symbol="SPSK",
        accession=SPSK_ACCESSION,
    )


def load_spsk_nport_snapshot():
    xml_text = build_spsk_nport_fixed_income_xml()
    return parse_official_nport_xml(xml_text, symbol="SPSK", accession=SPSK_ACCESSION)
