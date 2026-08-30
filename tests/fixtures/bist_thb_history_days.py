"""Tiny official-shaped THB rows for CI. Not live issuer authority."""

from __future__ import annotations

from datetime import date, timedelta

from services.bist_eod_bulletin import official_equity_series, thb_download_url, thb_member_name
from services.bist_thb_history import ADJUST_RAW, BistHistoricalPrice, SOURCE_THB_HISTORY


HEADER = (
    "TARIH;ISLEM KODU;BULTEN ADI;PAZAR GRUBU;PAZAR;YAPISAL BAZDA PIYASA ALT BOLUMU;"
    "ENSTRUMAN GRUBU;ENSTRUMAN TIPI;ENSTRUMAN SINIFI;ISLEM YONTEMI;PIYASA YAPICI;"
    "BIST 100 ENDEKS;BIST 30 ENDEKS;BRUT TAKAS;OZSERMAYE HALI;GECICI DURDURMA;"
    "ONCEKI KAPANIS FIYATI;ACILIS FIYATI;ACILIS SEANSI FIYATI;EN DUSUK FIYAT;"
    "EN YUKSEK FIYAT;KAPANIS FIYATI;KAPANIS SEANSI FIYATI;DEGISIM (%);"
    "BEKLEYEN EN IYI ALIS;BEKLEYEN EN IYI SATIS;A.O.F;TOPLAM ISLEM HACMI;"
    "TOPLAM ISLEM ADEDI;TOPLAM SOZLESME SAYISI;REFERANS FIYAT"
)
HEADER_EN = (
    "TRADE DATE;INSTRUMENT SERIES CODE;INSTRUMENT NAME;MARKET SUB SEGMENT;"
    "MARKET SEGMENT;MARKET;INSTRUMENT GROUP;INSTRUMENT TYPE;INSTRUMENT CLASS;"
    "TRADING METHOD;MARKET MAKER;BIST 100 INDEX;BIST 30 INDEX;GROSS SETTLEMENT;"
    "CORPORATE ACTION;SUSPENDED;PREVIOUS LAST PRICE;OPENING PRICE;"
    "OPENING SESSION PRICE;LOWEST PRICE;HIGHEST PRICE;CLOSING PRICE;"
    "CLOSING SESSION PRICE;CHANGE TO PREVIOUS CLOSING (%);REMAINING BID;"
    "REMAINING ASK;VWAP;TOTAL TRADED VALUE;TOTAL TRADED VOLUME;"
    "TOTAL NUMBER OF CONTRACTS;REFERENCE PRICE"
)


def equity_row(
    trading_date: date,
    symbol: str,
    close: float,
    *,
    corporate_action: str = "0",
    previous_close: float = 0.0,
) -> str:
    series = official_equity_series(symbol)
    return (
        f"{trading_date.isoformat()};{series};NAME;;Z;MSPOT;EQT;MSPOTEQT;MSPOTEQT{symbol};"
        f"SI;0;1;1;0;{corporate_action};;{previous_close};{close};{close};{close};{close};"
        f"{close};{close};0;{close};{close};{close};0;0;0;0"
    )


def thb_csv(trading_date: date, rows: list[str]) -> str:
    return "\n".join([HEADER, HEADER_EN, *rows]) + "\n"


def historical_row(
    symbol: str,
    trading_date: date,
    close: float,
    *,
    corporate_action_flag: str = "",
    currency: str = "TRY",
) -> BistHistoricalPrice:
    return BistHistoricalPrice(
        symbol=symbol,
        trade_date=trading_date,
        close=close,
        currency=currency,
        series=official_equity_series(symbol),
        market="MSPOT",
        source=SOURCE_THB_HISTORY,
        source_url=thb_download_url(trading_date),
        source_file=thb_member_name(trading_date),
        observed_at="2026-08-30T00:00:00+00:00",
        adjustment_status=ADJUST_RAW,
        previous_close=None,
        corporate_action_flag=corporate_action_flag,
    )


def weekday_series(
    symbol: str,
    *,
    end: date,
    calendar_days: int,
    start_price: float = 100.0,
    daily_step: float = 0.05,
) -> tuple[BistHistoricalPrice, ...]:
    rows: list[BistHistoricalPrice] = []
    first = end - timedelta(days=calendar_days - 1)
    cursor = first
    index = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(historical_row(symbol, cursor, start_price + index * daily_step))
            index += 1
        cursor += timedelta(days=1)
    return tuple(rows)
