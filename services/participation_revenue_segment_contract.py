from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from services.participation_intelligence_contract import CONFIDENCE_LOW

CLASSIFICATION_NON_PERMISSIBLE = "NON_PERMISSIBLE"
CLASSIFICATION_PERMISSIBLE = "PERMISSIBLE"
CLASSIFICATION_UNKNOWN = "UNKNOWN"

SOURCE_TYPE_SEC_XBRL = "sec_xbrl"
SOURCE_TYPE_CANDIDATE = "candidate_record"


@dataclass(frozen=True)
class RevenueSegmentEvidence:
    segment_id: str
    segment_name: str
    revenue_amount: Optional[float] = None
    revenue_pct: Optional[float] = None
    fiscal_period: Optional[str] = None
    filing_date: Optional[str] = None
    source: str = "SEC"
    source_type: str = SOURCE_TYPE_SEC_XBRL
    classification_code: str = CLASSIFICATION_UNKNOWN
    category: str = ""
    confidence: str = CONFIDENCE_LOW
    limitations: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
