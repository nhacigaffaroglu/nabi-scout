from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FxRateRow:
    base_currency: str
    quote_currency: str
    rate: float
    rate_date: str
    source: str
    data_quality: str
    stale: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FxConversionResult:
    native_amount: Optional[float]
    native_currency: str
    converted_amount: Optional[float]
    base_currency: str
    rate_used: Optional[float]
    rate_date: Optional[str]
    converted: bool
    unavailable: bool
    stale: bool
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
