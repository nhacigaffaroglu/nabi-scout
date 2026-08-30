"""Official KAP/Borsa CA evidence inside the 1Y THB window. Pilot audit only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from services.bist_corporate_action_audit import (
    EVENT_BONUS,
    EVENT_CASH_DIVIDEND,
    OfficialCorporateAction,
    SOURCE_THEORETICAL,
)


def official_window_events() -> tuple[OfficialCorporateAction, ...]:
    return (
        OfficialCorporateAction(
            symbol="ASELS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2025, 11, 25),
            official_source="https://www.kap.org.tr/tr/Bildirim/1443371",
            amount=Decimal("0.2346491"),
            adjustment_required=False,
            notes=("nakit_kar_payi_ex_date",),
        ),
        OfficialCorporateAction(
            symbol="BIMAS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2025, 9, 17),
            official_source="https://www.kap.org.tr/tr/Bildirim",
            adjustment_required=False,
            notes=("nakit_kar_payi_taksit",),
        ),
        OfficialCorporateAction(
            symbol="BIMAS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2025, 12, 17),
            official_source="https://www.kap.org.tr/tr/Bildirim",
            adjustment_required=False,
            notes=("nakit_kar_payi_taksit",),
        ),
        OfficialCorporateAction(
            symbol="BIMAS",
            event_type=EVENT_BONUS,
            effective_date=date(2026, 5, 14),
            official_source="https://www.kap.org.tr/tr/Bildirim/1610850",
            ratio=Decimal("1"),
            adjustment_required=True,
            notes=("bedelsiz_100_pct_n1_1", SOURCE_THEORETICAL),
        ),
        OfficialCorporateAction(
            symbol="BIMAS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2026, 6, 17),
            official_source="https://www.kap.org.tr/tr/Bildirim",
            amount=Decimal("2.0"),
            adjustment_required=False,
            notes=("nakit_kar_payi_taksit",),
        ),
        OfficialCorporateAction(
            symbol="TUPRS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2025, 9, 30),
            official_source="https://www.kap.org.tr/tr/Bildirim",
            adjustment_required=False,
            notes=("nakit_kar_payi_ex_date",),
        ),
        OfficialCorporateAction(
            symbol="TUPRS",
            event_type=EVENT_CASH_DIVIDEND,
            effective_date=date(2026, 3, 16),
            official_source="https://www.kap.org.tr/tr/Bildirim",
            amount=Decimal("10.3799282"),
            adjustment_required=False,
            notes=("nakit_kar_payi_taksit",),
        ),
    )
