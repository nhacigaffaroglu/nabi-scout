from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.wealth_timeline_contract import PortfolioSnapshotView


@dataclass(frozen=True)
class PortfolioChangeEvent:
    code: str
    severity: str
    title: str
    detail: str
    metric_value: Optional[float] = None
    previous_value: Optional[float] = None
    affected_symbols: Tuple[str, ...] = ()


def _payload_positions(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    positions = payload.get("priced_positions") or payload.get("positions") or []
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        by_symbol[symbol] = row
    return by_symbol


def _allocation_map(payload: Dict[str, Any], key: str) -> Dict[str, float]:
    rows = payload.get(key) or []
    result: Dict[str, float] = {}
    for row in rows:
        label = str(row.get("label") or row.get("key") or "")
        weight = row.get("weight_pct")
        if label and weight is not None:
            result[label] = float(weight)
    return result


def compare_portfolio_snapshots(
    previous: PortfolioSnapshotView,
    current: PortfolioSnapshotView,
) -> Tuple[PortfolioChangeEvent, ...]:
    events: List[PortfolioChangeEvent] = []
    prev_payload = previous.valuation_payload or {}
    curr_payload = current.valuation_payload or {}

    value_delta = current.priced_market_value - previous.priced_market_value
    if abs(value_delta) >= 1.0:
        events.append(
            PortfolioChangeEvent(
                code="PORTFOLIO_VALUE_CHANGE",
                severity="info",
                title="Portföy değeri değişti",
                detail=(
                    f"Portföy değeri {previous.priced_market_value:,.2f} "
                    f"{previous.base_currency} → "
                    f"{current.priced_market_value:,.2f} "
                    f"{current.base_currency}."
                ),
                metric_value=value_delta,
                previous_value=previous.priced_market_value,
            )
        )

    prev_positions = _payload_positions(prev_payload)
    curr_positions = _payload_positions(curr_payload)
    for symbol, row in curr_positions.items():
        prev = prev_positions.get(symbol)
        if prev is None:
            events.append(
                PortfolioChangeEvent(
                    code="NEW_HOLDING",
                    severity="info",
                    title=f"Yeni pozisyon: {symbol}",
                    detail=f"{symbol} portföye eklendi.",
                    affected_symbols=(symbol,),
                )
            )
            continue
        prev_w = prev.get("weight_pct")
        curr_w = row.get("weight_pct")
        if prev_w is not None and curr_w is not None:
            delta = float(curr_w) - float(prev_w)
            if abs(delta) >= 0.5:
                events.append(
                    PortfolioChangeEvent(
                        code="WEIGHT_CHANGE",
                        severity="watch" if abs(delta) >= 2.0 else "info",
                        title=f"{symbol} ağırlığı değişti",
                        detail=(
                            f"{symbol} ağırlığı %{float(prev_w):.1f}'den "
                            f"%{float(curr_w):.1f}'e "
                            f"{'yükseldi' if delta > 0 else 'düştü'}."
                        ),
                        metric_value=float(curr_w),
                        previous_value=float(prev_w),
                        affected_symbols=(symbol,),
                    )
                )

    for symbol in prev_positions:
        if symbol not in curr_positions:
            events.append(
                PortfolioChangeEvent(
                    code="CLOSED_HOLDING",
                    severity="info",
                    title=f"Pozisyon kapandı: {symbol}",
                    detail=f"{symbol} artık açık pozisyonlarda görünmüyor.",
                    affected_symbols=(symbol,),
                )
            )

    prev_sector = _allocation_map(prev_payload, "sector_allocation")
    curr_sector = _allocation_map(curr_payload, "sector_allocation")
    for label, weight in curr_sector.items():
        prev_weight = prev_sector.get(label)
        if prev_weight is not None:
            delta = weight - prev_weight
            if abs(delta) >= 1.0:
                events.append(
                    PortfolioChangeEvent(
                        code="SECTOR_ALLOCATION_CHANGE",
                        severity="info",
                        title=f"Sektör dağılımı: {label}",
                        detail=(
                            f"{label} sektör yoğunluğu "
                            f"{delta:+.1f} puan değişti."
                        ),
                        metric_value=weight,
                        previous_value=prev_weight,
                    )
                )

    prev_cov = float(prev_payload.get("research_coverage_weight_pct") or 0.0)
    curr_cov = float(curr_payload.get("research_coverage_weight_pct") or 0.0)
    if abs(curr_cov - prev_cov) >= 1.0:
        events.append(
            PortfolioChangeEvent(
                code="RESEARCH_COVERAGE_CHANGE",
                severity="info",
                title="Araştırma kapsamı değişti",
                detail=(
                    f"Portföy araştırma kapsamı %{prev_cov:.0f}'den "
                    f"%{curr_cov:.0f}'e değişti."
                ),
                metric_value=curr_cov,
                previous_value=prev_cov,
            )
        )

    if current.unpriced_position_count > previous.unpriced_position_count:
        events.append(
            PortfolioChangeEvent(
                code="NEW_UNPRICED_POSITIONS",
                severity="watch",
                title="Yeni fiyatlanamayan pozisyon",
                detail=(
                    f"Fiyatlanamayan pozisyon sayısı "
                    f"{previous.unpriced_position_count} → "
                    f"{current.unpriced_position_count}."
                ),
                metric_value=float(current.unpriced_position_count),
                previous_value=float(previous.unpriced_position_count),
            )
        )

    return tuple(events)
