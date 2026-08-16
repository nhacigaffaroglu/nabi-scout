from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


FX_ATTRIBUTION_UNAVAILABLE = "FX_ATTRIBUTION_UNAVAILABLE"


@dataclass(frozen=True)
class FxAttributionView:
    status: str
    local_return_pct: Optional[float]
    fx_translation_pct: Optional[float]
    interaction_pct: Optional[float]
    combined_return_pct: Optional[float]
    limitation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_fx_attribution_view(
    *,
    symbol: str,
    native_currency: str,
    base_currency: str,
) -> FxAttributionView:
    """Deterministic FX attribution — unavailable unless historical evidence exists."""
    _ = (symbol, native_currency, base_currency)
    return FxAttributionView(
        status=FX_ATTRIBUTION_UNAVAILABLE,
        local_return_pct=None,
        fx_translation_pct=None,
        interaction_pct=None,
        combined_return_pct=None,
        limitation=(
            "Geçmiş varlık fiyatı ve FX kanıtı yeterli değil; "
            "getiri ayrıştırması yapılmadı."
        ),
    )
