"""Captured official SPRE/SPWO N-PORT country and denomination evidence.

Uses the canonical N-PORT exposure parser. No ticker/name/ISIN country guessing.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from services.official_fund_nport import parse_official_nport_exposure

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_nport_evidence"

NPORT_EXPOSURE_META = {
    "SPRE": {
        "accession": "0002000324-26-003236",
        "as_of": "2026-05-31",
        "cik": "0001742912",
        "series_id": "S000070461",
        "class_id": "C000223966",
        "series_name": "SP Funds S&P Global REIT Sharia ETF",
    },
    "SPWO": {
        "accession": "0000894189-26-018183",
        "as_of": "2026-04-30",
        "cik": "0001989916",
        "series_id": "S000083496",
        "class_id": "C000247153",
        "series_name": "SP Funds S&P World (ex-US) ETF",
    },
}


def _xml_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA"}:
        return ""
    return escape(text)


def build_nport_exposure_xml(symbol: str) -> str:
    fund = str(symbol or "").strip().upper()
    meta = NPORT_EXPOSURE_META[fund]
    path = EVIDENCE_DIR / f"{fund}_nport_holdings.tsv"
    holdings: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 10:
            continue
        name, title, cusip, isin, pct, country, cur, cur_cond, asset_cat, issuer_cat = parts[:10]
        cur_xml = (
            f"      <curCd>{_xml_text(cur)}</curCd>\n"
            if _xml_text(cur)
            else f"      <currencyConditional curCd=\"{_xml_text(cur_cond)}\"/>\n"
        )
        holdings.append(
            "    <invstOrSec>\n"
            f"      <name>{_xml_text(name)}</name>\n"
            f"      <title>{_xml_text(title)}</title>\n"
            f"      <cusip>{_xml_text(cusip) or 'N/A'}</cusip>\n"
            f"      <identifiers><isin value=\"{_xml_text(isin)}\"/></identifiers>\n"
            f"      <pctVal>{escape(pct)}</pctVal>\n"
            f"      <invCountry>{_xml_text(country)}</invCountry>\n"
            f"{cur_xml}"
            f"      <assetCat>{_xml_text(asset_cat)}</assetCat>\n"
            f"      <issuerCat>{_xml_text(issuer_cat)}</issuerCat>\n"
            "    </invstOrSec>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">\n'
        "  <headerData>\n"
        "    <submissionType>NPORT-P</submissionType>\n"
        f"    <accessionNumber>{meta['accession']}</accessionNumber>\n"
        f"    <filerInfo><filer><issuerCredentials><cik>{meta['cik']}</cik></issuerCredentials></filer></filerInfo>\n"
        "  </headerData>\n"
        "  <genInfo>\n"
        f"    <seriesId>{meta['series_id']}</seriesId>\n"
        f"    <seriesName>{escape(meta['series_name'])}</seriesName>\n"
        f"    <classId>{meta['class_id']}</classId>\n"
        f"    <repPdDate>{meta['as_of']}</repPdDate>\n"
        "  </genInfo>\n"
        "  <invstOrSecs>\n"
        + "\n".join(holdings)
        + "\n  </invstOrSecs>\n"
        "</edgarSubmission>\n"
    )


def load_official_nport_exposure(symbol: str):
    fund = str(symbol or "").strip().upper()
    if fund not in NPORT_EXPOSURE_META:
        return None
    return parse_official_nport_exposure(
        build_nport_exposure_xml(fund),
        symbol=fund,
        accession=NPORT_EXPOSURE_META[fund]["accession"],
    )
