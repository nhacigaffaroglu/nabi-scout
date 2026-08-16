from __future__ import annotations

from datetime import date
from typing import List, Tuple

from services.monitor_contract import MonitorEventDraft
from services.monitor_materiality_engine import apply_materiality_to_draft


def detect_fx_stale_events(
    *,
    user_id: str,
    portfolio_id: str,
    stale_pairs: Tuple[str, ...],
) -> Tuple[MonitorEventDraft, ...]:
    if not stale_pairs:
        return ()
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol="FX",
        event_type="FX_RATE_STALE",
        event_category="wealth",
        severity="watch",
        materiality="medium",
        occurred_at=date.today().isoformat(),
        dedupe_key=f"wave4:{portfolio_id}:fx_stale",
        title="Döviz kurları güncel değil",
        summary=f"Eski kur çiftleri: {', '.join(stale_pairs[:5])}",
        event_payload={"stale_pairs": list(stale_pairs[:10])},
        notification_eligible=False,
    )
    return (apply_materiality_to_draft(draft),)


def detect_missing_price_events(
    *,
    user_id: str,
    portfolio_id: str,
    symbols: Tuple[str, ...],
) -> Tuple[MonitorEventDraft, ...]:
    drafts: List[MonitorEventDraft] = []
    for symbol in symbols[:5]:
        draft = MonitorEventDraft(
            user_id=user_id,
            portfolio_id=portfolio_id,
            symbol=symbol,
            event_type="ASSET_PRICE_MISSING",
            event_category="wealth",
            severity="watch",
            materiality="medium",
            occurred_at=date.today().isoformat(),
            dedupe_key=f"wave4:{portfolio_id}:price_missing:{symbol}",
            title=f"{symbol} fiyatı eksik",
            summary="Fiyatlanmamış pozisyon; toplam servet kısmi olabilir.",
            event_payload={"symbol": symbol},
            notification_eligible=False,
        )
        drafts.append(apply_materiality_to_draft(draft))
    return tuple(drafts)


def detect_fund_holdings_updated_events(
    *,
    user_id: str,
    portfolio_id: str,
    symbols: Tuple[str, ...],
) -> Tuple[MonitorEventDraft, ...]:
    if not symbols:
        return ()
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol=symbols[0],
        event_type="FUND_HOLDINGS_UPDATED",
        event_category="wealth",
        severity="info",
        materiality="low",
        occurred_at=date.today().isoformat(),
        dedupe_key=f"wave4:{portfolio_id}:fund_holdings_updated",
        title="Fon holding verisi güncellendi",
        summary=f"{len(symbols)} fon/ETF için persisted holding snapshot mevcut.",
        event_payload={"symbols": list(symbols[:10])},
        notification_eligible=False,
    )
    return (apply_materiality_to_draft(draft),)


def detect_fund_participation_changed_events(
    *,
    user_id: str,
    portfolio_id: str,
    symbols: Tuple[str, ...],
) -> Tuple[MonitorEventDraft, ...]:
    if not symbols:
        return ()
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol=symbols[0],
        event_type="FUND_PARTICIPATION_CHANGED",
        event_category="wealth",
        severity="watch",
        materiality="medium",
        occurred_at=date.today().isoformat(),
        dedupe_key=f"wave4:{portfolio_id}:fund_participation_changed:{symbols[0]}",
        title="Fon katılım maruziyeti değişti",
        summary="Alt holding kanıtına göre fon katılım dağılımı güncellendi.",
        event_payload={"symbols": list(symbols[:10])},
        notification_eligible=False,
    )
    return (apply_materiality_to_draft(draft),)


def detect_fund_holdings_stale_events(
    *,
    user_id: str,
    portfolio_id: str,
    symbols: Tuple[str, ...],
) -> Tuple[MonitorEventDraft, ...]:
    if not symbols:
        return ()
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol=symbols[0],
        event_type="FUND_HOLDINGS_STALE",
        event_category="wealth",
        severity="info",
        materiality="low",
        occurred_at=date.today().isoformat(),
        dedupe_key=f"wave4:{portfolio_id}:fund_holdings_stale",
        title="Fon holding verisi eski",
        summary=f"{len(symbols)} fon/ETF holding snapshot güncellenmeli.",
        event_payload={"symbols": list(symbols[:10])},
        notification_eligible=False,
    )
    return (apply_materiality_to_draft(draft),)


def detect_allocation_change_events(
    *,
    user_id: str,
    portfolio_id: str,
    asset_class_changed: bool,
    currency_changed: bool,
) -> Tuple[MonitorEventDraft, ...]:
    drafts: List[MonitorEventDraft] = []
    if asset_class_changed:
        draft = MonitorEventDraft(
            user_id=user_id,
            portfolio_id=portfolio_id,
            symbol=None,
            event_type="ASSET_CLASS_ALLOCATION_CHANGED",
            event_category="wealth",
            severity="info",
            materiality="low",
            occurred_at=date.today().isoformat(),
            dedupe_key=f"wave4:{portfolio_id}:asset_class_changed",
            title="Varlık sınıfı dağılımı değişti",
            summary="Günlük snapshot karşılaştırmasında anlamlı değişim.",
            event_payload={},
            notification_eligible=False,
        )
        drafts.append(apply_materiality_to_draft(draft))
    if currency_changed:
        draft = MonitorEventDraft(
            user_id=user_id,
            portfolio_id=portfolio_id,
            symbol=None,
            event_type="CURRENCY_EXPOSURE_CHANGED",
            event_category="wealth",
            severity="info",
            materiality="low",
            occurred_at=date.today().isoformat(),
            dedupe_key=f"wave4:{portfolio_id}:currency_exposure_changed",
            title="Para birimi maruziyeti değişti",
            summary="FX veya pozisyon değişimi para birimi dağılımını etkiledi.",
            event_payload={},
            notification_eligible=False,
        )
        drafts.append(apply_materiality_to_draft(draft))
    return tuple(drafts)
