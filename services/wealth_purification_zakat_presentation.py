"""Copy for Arındırma & Zekât. No calculation and no religious rulings."""

from __future__ import annotations

from typing import Optional

from services.wealth_goal_center_presentation import format_money_display, format_pct_display
from services.wealth_purification_zakat import (
    CASH_UNAVAILABLE,
    STATUS_LIMITED,
    STATUS_MISSING_INPUT,
    STATUS_READY,
    PurificationBasis,
    PurificationZakatResult,
    PurificationZakatRow,
)

SECTION_TITLE = "Arındırma & Zekât"
SECTION_SUMMARY = "Özet"
SECTION_PRODUCTS = "Ürün bazında"
SECTION_ASSUMPTIONS = "Varsayımlar"
SECTION_MISSING = "Eksik Bilgiler"
DISCLAIMER = (
    "Bu ekran kullanıcı tarafından girilen varsayımlara göre matematiksel "
    "hesaplama yapar; dini hüküm veya fetva üretmez."
)
BASIS_DIVIDEND_LABEL = "Temettü / gelir matrahı"
BASIS_MARKET_LABEL = "Güncel piyasa değeri matrahı"
BASIS_UNSELECTED_LABEL = "Matrah seçilmedi"
ZAKAT_RATE_LABEL = "Zekât oranı (%)"
ZAKAT_RATE_HELP = (
    "Kullanıcı varsayımıdır; motor dini hüküm üretmez. Varsayılan 2.5 yalnızca "
    "düzenlenebilir bir başlangıç değeridir."
)
GLOBAL_ELIGIBLE_LABEL = "Tüm uygun varlıkları %100 dahil et"
GLOBAL_ELIGIBLE_HELP = (
    "Senaryo kontrolü. Kalıcı kayıt yazılmaz; girilmemiş zekât dahil oranını "
    "bu oturumda %100 kabul eder."
)
STATUS_LABELS = {
    STATUS_READY: "Hazır",
    STATUS_MISSING_INPUT: "Eksik girdi",
    STATUS_LIMITED: "Kısıtlı",
}


def basis_label(basis: Optional[PurificationBasis]) -> str:
    if basis is PurificationBasis.DIVIDEND_INCOME:
        return BASIS_DIVIDEND_LABEL
    if basis is PurificationBasis.MARKET_VALUE:
        return BASIS_MARKET_LABEL
    return BASIS_UNSELECTED_LABEL


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def money_or_dash(value: Optional[float], currency: str) -> str:
    if value is None:
        return "—"
    return format_money_display(value, currency)


def pct_or_dash(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return format_pct_display(value)


def row_status_label(row: PurificationZakatRow) -> str:
    return status_label(row.status)


def missing_product_lines(result: PurificationZakatResult) -> tuple[str, ...]:
    lines: list[str] = []
    for row in result.rows:
        if row.status != STATUS_MISSING_INPUT:
            continue
        notes = ", ".join(row.missing_notes) if row.missing_notes else "Eksik girdi"
        lines.append(f"{row.symbol} · {row.institution} · {notes}")
    return tuple(lines)


def cash_label(result: PurificationZakatResult, currency: str) -> str:
    if not result.cash_available:
        return CASH_UNAVAILABLE
    cash_zakat = sum(
        (row.zakat_amount or 0.0)
        for row in result.rows
        if row.is_cash and row.zakat_amount is not None
    )
    if any(row.is_cash and row.zakat_amount is None for row in result.rows):
        return CASH_UNAVAILABLE if not any(row.is_cash for row in result.rows) else money_or_dash(cash_zakat, currency)
    return money_or_dash(cash_zakat, currency)
