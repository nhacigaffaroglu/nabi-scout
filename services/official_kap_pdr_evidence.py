"""Load captured official KAP Portföy Dağılım Raporu evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.official_kap_pdr import (
    discover_latest_pdr,
    parse_kap_pdr_text,
)
from services.official_tefas import normalize_fund_code

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_kap_pdr_evidence"
DISCOVERY_PATH = EVIDENCE_DIR / "pdr_discovery_rows.json"
ATTACHMENT_PATH = EVIDENCE_DIR / "pdr_attachment_excerpts.json"
PDR_TEXT = {
    "AIS": EVIDENCE_DIR / "AIS_2026.07.txt",
    "ZPE": EVIDENCE_DIR / "ZPE_2026.07.txt",
    "IAT": EVIDENCE_DIR / "IAT_2026.07.txt",
}


def load_pdr_discovery_rows() -> list[dict[str, Any]]:
    payload = json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))
    return [dict(row) for row in payload.get("rows") or []]


def load_pdr_attachment_excerpts() -> dict[str, dict[str, Any]]:
    return json.loads(ATTACHMENT_PATH.read_text(encoding="utf-8"))


def load_pdr_text(fund_code: str) -> str:
    code = normalize_fund_code(fund_code)
    path = PDR_TEXT.get(code)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"captured PDR text missing for {code}")
    return path.read_text(encoding="utf-8")


def load_captured_pdr_discovery(fund_code: str):
    return discover_latest_pdr(
        load_pdr_discovery_rows(),
        fund_code,
        attachments=load_pdr_attachment_excerpts(),
    )


def load_captured_pdr_holdings(fund_code: str):
    code = normalize_fund_code(fund_code)
    if code not in PILOT_TEFAS_FUND_CODES:
        raise ValueError(f"unsupported_pdr_fund:{code or fund_code}")
    discovery = load_captured_pdr_discovery(code)
    if not discovery.resolved:
        raise ValueError(f"pdr_unresolved:{code}")
    return parse_kap_pdr_text(
        load_pdr_text(code),
        fund_code=code,
        report_period=discovery.report_period,
        report_date=None,
        source_notification_id=str(discovery.disclosure_index) if discovery.disclosure_index else None,
        source_attachment=discovery.attachment_name,
        source_url=discovery.source_url,
    )
