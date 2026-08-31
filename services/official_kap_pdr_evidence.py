"""Load captured official KAP Portföy Dağılım Raporu evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from services.official_kap_pdr import (
    KapPdrError,
    discover_latest_pdr,
    parse_kap_pdr_text,
    report_period_label,
)
from services.official_tefas import normalize_fund_code
from services.turkiye_fund_source_capture import cached_pdr_text_path

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_kap_pdr_evidence"
DISCOVERY_PATH = EVIDENCE_DIR / "pdr_discovery_rows.json"
ATTACHMENT_PATH = EVIDENCE_DIR / "pdr_attachment_excerpts.json"
PDR_TEXT = {
    "AIS": EVIDENCE_DIR / "AIS_2026.07.txt",
    "ZPE": EVIDENCE_DIR / "ZPE_2026.07.txt",
    "IAT": EVIDENCE_DIR / "IAT_2026.07.txt",
}
_PDR_FILENAME = re.compile(r"^([A-Z0-9]+)_(20\d{2})\.(\d{2})\.txt$")


def load_pdr_discovery_rows() -> list[dict[str, Any]]:
    payload = json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))
    return [dict(row) for row in payload.get("rows") or []]


def load_pdr_attachment_excerpts() -> dict[str, dict[str, Any]]:
    return json.loads(ATTACHMENT_PATH.read_text(encoding="utf-8"))


def captured_pdr_text_path(fund_code: str) -> Optional[Path]:
    code = normalize_fund_code(fund_code)
    explicit = PDR_TEXT.get(code)
    if explicit is not None and explicit.is_file():
        return explicit
    matches = sorted(EVIDENCE_DIR.glob(f"{code}_*.txt"))
    if matches:
        return matches[-1]
    return cached_pdr_text_path(code)


def _period_from_filename(path: Path) -> Optional[str]:
    match = _PDR_FILENAME.match(path.name)
    if not match:
        return None
    return report_period_label(match.group(2), match.group(3))


def load_pdr_text(fund_code: str) -> str:
    path = captured_pdr_text_path(fund_code)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"captured PDR text missing for {normalize_fund_code(fund_code)}")
    return path.read_text(encoding="utf-8")


def load_captured_pdr_discovery(fund_code: str, *, as_of=None):
    return discover_latest_pdr(
        load_pdr_discovery_rows(),
        fund_code,
        attachments=load_pdr_attachment_excerpts(),
        as_of=as_of,
    )


def load_captured_pdr_holdings(fund_code: str, *, as_of=None):
    code = normalize_fund_code(fund_code)
    path = captured_pdr_text_path(code)
    if path is None:
        raise FileNotFoundError(f"captured PDR text missing for {code or fund_code}")
    discovery = load_captured_pdr_discovery(code, as_of=as_of)
    period = discovery.report_period if discovery.resolved else _period_from_filename(path)
    return parse_kap_pdr_text(
        load_pdr_text(code),
        fund_code=code,
        report_period=period,
        report_date=None,
        source_notification_id=str(discovery.disclosure_index) if discovery.disclosure_index else None,
        source_attachment=discovery.attachment_name,
        source_url=discovery.source_url if discovery.resolved else "",
    )


def try_load_captured_pdr_holdings(fund_code: str, *, as_of=None):
    try:
        return load_captured_pdr_holdings(fund_code, as_of=as_of)
    except (FileNotFoundError, ValueError, OSError, KapPdrError):
        return None
