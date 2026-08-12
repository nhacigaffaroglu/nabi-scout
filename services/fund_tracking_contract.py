from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

TRACKED_FUND_COLUMNS = frozenset({
    "symbol",
    "fund_name",
    "exchange",
    "asset_class",
    "participation_status",
    "participation_score",
    "participation_source",
    "data_provider",
    "resolution_source",
    "last_reviewed_at",
    "updated_at",
})


@dataclass(frozen=True)
class TrackedFund:
    symbol: str
    fund_name: Optional[str] = None
    exchange: Optional[str] = None
    asset_class: Optional[str] = None
    participation_status: Optional[str] = None
    participation_score: Optional[int] = None
    participation_source: Optional[str] = None
    data_provider: Optional[str] = None
    resolution_source: Optional[str] = None
    last_reviewed_at: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare_tracked_fund_payload(
    payload: Dict[str, Any],
    *,
    touch_last_reviewed: bool = True,
) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in payload.items():
        if key not in TRACKED_FUND_COLUMNS:
            continue
        if value is None or value == "":
            continue
        cleaned[key] = value
    symbol = str(cleaned.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("Sembol gerekli.")
    cleaned["symbol"] = symbol
    cleaned["updated_at"] = _now_iso()
    if touch_last_reviewed and cleaned.get("last_reviewed_at") is None:
        cleaned["last_reviewed_at"] = cleaned["updated_at"]
    score = cleaned.get("participation_score")
    if score is not None:
        cleaned["participation_score"] = int(score)
    return cleaned
