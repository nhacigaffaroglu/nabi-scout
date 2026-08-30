"""User-facing copy for new-money allocation. No allocation math."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from services.wealth_goal_center_presentation import format_money_display
from services.wealth_new_money_allocation import (
    AllocationRecommendation,
    AllocationSkip,
    REASON_BELOW_MIN_TRADE,
    REASON_CANDIDATE,
    REASON_CONCENTRATION_LIMIT,
    REASON_DATA_INCOMPLETE,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_FX_REQUIRED,
    REASON_INSUFFICIENT_CASH,
    REASON_LAYER_DEFICIT,
    REASON_MIX_MAINTENANCE,
    REASON_NOT_ACTIONABLE,
    REASON_OVERWEIGHT_LAYER,
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    REASON_PARTICIPATION_BLOCKED,
    REASON_STRONG_CANDIDATE,
)

SECTION_TITLE = "Yeni Para Dağılımı"
MODE_MONTHLY = "Aylık Katkı"
MODE_EXTRA = "Ekstra Para"
AMOUNT_LABEL = "Tutar"
MIN_TRADE_LABEL = "Minimum işlem tutarı"
RUN_LABEL = "Dağılım Önerisi Oluştur"
EXISTING_LABEL = "Mevcut pozisyon"
NEW_LABEL = "Yeni fırsat"
TOTAL_ALLOCATED_LABEL = "Toplam kullanılacak"
RESIDUAL_LABEL = "Kalan nakit"
SKIPPED_EXPANDER = "Neden bazı ürünler seçilmedi?"
DETAILS_EXPANDER = "Detaylar"
ALLOCATION_SCENARIO_POINTER = (
    "Katkı planını uygulamak için dağılım senaryosunu görüntüle"
)
MONTHLY_CAPTION = "Katkı planındaki aylık tutar. Senaryo; planı değiştirmez."
EXTRA_CAPTION = "Geçici senaryo tutarı. Kaydedilmez."
MIN_TRADE_CAPTION = "Yalnızca bu senaryo için. Portföy politikasına yazılmaz."
RESIDUAL_NOTE = (
    "Tam pay veya minimum işlem kuralları nakit bırakabilir; kalanı zorla dağıtılmaz."
)
SCENARIO_DISCLAIMER = "Öneri senaryosudur. Alım emri yok; kayıt yazılmaz."

USER_REASON_LABELS = {
    REASON_LAYER_DEFICIT: "Hedef katmanda açık var.",
    REASON_EXISTING_HOLDING_TOPUP: "Mevcut pozisyonu hedef ağırlığa yaklaştırıyor.",
    REASON_STRONG_CANDIDATE: "Güçlü aday.",
    REASON_CANDIDATE: "Aday.",
    REASON_MIX_MAINTENANCE: "Hedef karışımı korumak için dağıtılır.",
}

SKIP_REASON_LABELS = {
    REASON_OVERWEIGHT_LAYER: "Katman hedef ağırlığın üzerinde.",
    REASON_BELOW_MIN_TRADE: "Minimum işlem tutarının altında.",
    REASON_NOT_ACTIONABLE: "İşlem yapılabilir karar yok.",
    REASON_INSUFFICIENT_CASH: "Tek lot için nakit yetersiz.",
    REASON_PARTICIPATION_BLOCKED: "Katılım uygun olmadığı için eklenmez.",
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED: "8E exposure artışına izin vermiyor.",
    REASON_CONCENTRATION_LIMIT: "Tek pozisyon yoğunluk eşiği aşılır.",
    REASON_FX_REQUIRED: "Gerekli kur dönüşümü yok.",
}

_PRICE_HINTS = ("fiyat", "price")


def holding_kind_label(existing_or_new: str) -> str:
    if existing_or_new == "existing":
        return EXISTING_LABEL
    return NEW_LABEL


def recommendation_reason_label(row: AllocationRecommendation) -> str:
    parts: list[str] = []
    if REASON_LAYER_DEFICIT in (row.reason_text or "") or row.reason_code == REASON_LAYER_DEFICIT:
        parts.append(USER_REASON_LABELS[REASON_LAYER_DEFICIT])
    mapped = USER_REASON_LABELS.get(row.reason_code)
    if mapped and mapped not in parts:
        parts.append(mapped)
    return " ".join(parts) if parts else (row.reason_text or "")


def skip_reason_label(row: AllocationSkip) -> str:
    if row.reason_code == REASON_DATA_INCOMPLETE:
        text = (row.reason_text or "").lower()
        if any(hint in text for hint in _PRICE_HINTS):
            return "Fiyat eksik."
        return row.reason_text
    return SKIP_REASON_LABELS.get(row.reason_code, row.reason_text)


def format_quantity(quantity: Decimal) -> str:
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    text = format(quantity, "f").rstrip("0").rstrip(".")
    return text or "0"


def format_allocation_amount(value: Optional[Decimal], currency: str) -> str:
    return format_money_display(value, currency)


def residual_explanation(residual: Decimal) -> str:
    if residual > 0:
        return RESIDUAL_NOTE
    return ""
