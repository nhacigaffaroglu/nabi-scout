"""Conservative SEC 8-K item → Signal Intelligence taxonomy.

Only well-formed item numbers from SEC metadata are mapped.
Headline text is never used. 9.01 is an exhibit companion, not an event.
Unknown items stay OTHER. Missing items stay a single FORM_8K filing event.
"""

from __future__ import annotations

from typing import Optional

from services.signal_intelligence_contract import (
    EVENT_EARNINGS,
    EVENT_LEGAL_REGULATORY,
    EVENT_MANAGEMENT_CHANGE,
    EVENT_OTHER,
    EVENT_SEC_FILING,
    SUBTYPE_BANKRUPTCY,
    SUBTYPE_FORM_8K,
)


# Standalone logical items only. 9.01 is excluded on purpose.
SEC_8K_ITEM_MAP: dict[str, tuple[str, Optional[str]]] = {
    "1.01": (EVENT_OTHER, "ITEM_1_01"),
    "1.02": (EVENT_OTHER, "ITEM_1_02"),
    "1.03": (EVENT_LEGAL_REGULATORY, SUBTYPE_BANKRUPTCY),
    "2.01": (EVENT_OTHER, "ITEM_2_01"),
    "2.02": (EVENT_EARNINGS, "ITEM_2_02"),
    "2.03": (EVENT_OTHER, "ITEM_2_03"),
    "2.04": (EVENT_OTHER, "ITEM_2_04"),
    "2.05": (EVENT_OTHER, "ITEM_2_05"),
    "2.06": (EVENT_OTHER, "ITEM_2_06"),
    "3.01": (EVENT_OTHER, "ITEM_3_01"),
    "3.02": (EVENT_OTHER, "ITEM_3_02"),
    "3.03": (EVENT_OTHER, "ITEM_3_03"),
    "4.01": (EVENT_OTHER, "ITEM_4_01"),
    "4.02": (EVENT_OTHER, "ITEM_4_02"),
    "5.01": (EVENT_OTHER, "ITEM_5_01"),
    "5.02": (EVENT_MANAGEMENT_CHANGE, "ITEM_5_02"),
    "5.03": (EVENT_OTHER, "ITEM_5_03"),
    "5.04": (EVENT_OTHER, "ITEM_5_04"),
    "5.05": (EVENT_OTHER, "ITEM_5_05"),
    "5.06": (EVENT_OTHER, "ITEM_5_06"),
    "5.07": (EVENT_OTHER, "ITEM_5_07"),
    "5.08": (EVENT_OTHER, "ITEM_5_08"),
    "7.01": (EVENT_OTHER, "ITEM_7_01"),
    "8.01": (EVENT_OTHER, "ITEM_8_01"),
}

COMPANION_ITEMS = frozenset({"9.01"})


def map_sec_8k_item(item: str) -> tuple[str, Optional[str]]:
    key = str(item or "").strip()
    return SEC_8K_ITEM_MAP.get(key, (EVENT_OTHER, None))


def generic_8k_mapping() -> tuple[str, str]:
    return EVENT_SEC_FILING, SUBTYPE_FORM_8K
