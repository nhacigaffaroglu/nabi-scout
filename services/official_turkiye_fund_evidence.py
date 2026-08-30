"""Load captured official TEFAS/KAP evidence for Turkish fund pilots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EVIDENCE_DIR = Path(__file__).resolve().parent / "official_turkiye_fund_evidence"
TEFAS_SNAPSHOT_PATH = EVIDENCE_DIR / "tefas_official_snapshot.json"
KAP_EVIDENCE_PATH = EVIDENCE_DIR / "kap_official_evidence.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tefas_official_bundle() -> dict[str, Any]:
    return _load_json(TEFAS_SNAPSHOT_PATH)


def load_kap_official_bundle() -> dict[str, Any]:
    return _load_json(KAP_EVIDENCE_PATH)


def load_tefas_price_rows(fund_code: str, *, period_months: int = 12) -> list[dict[str, Any]]:
    code = str(fund_code or "").strip().upper()
    path = EVIDENCE_DIR / f"tefas_prices_{code}.json"
    payload = _load_json(path)
    rows = payload.get(str(period_months)) or payload.get(period_months) or []
    return [dict(row) for row in rows]
