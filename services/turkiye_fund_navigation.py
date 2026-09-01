"""Dashboard / Fund Report navigation for canonical Turkish FUND/TR identities.

Reuses PILOT_TEFAS_FUND_CODES. Does not call FMP, TEFAS, KAP, live analysis,
Fund Intelligence evaluate, or New Money. Navigation only selects existing
canonical production identity for snapshot-only Fund Report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping, Optional

from services.fund_decision_readiness import TURKIYE_FUND_8E_INSTRUMENT, TURKIYE_FUND_8E_MARKET
from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_TEFAS_FUND_CODES
from services.fund_report_service import (
    FUND_REPORT_QUERY_INSTRUMENT,
    FUND_REPORT_QUERY_MARKET,
    FUND_REPORT_QUERY_PARAM,
    FUND_REPORT_SESSION_INSTRUMENT,
    FUND_REPORT_SESSION_LIVE,
    FUND_REPORT_SESSION_MARKET,
    FUND_REPORT_SESSION_RESOLVED,
    FUND_REPORT_SESSION_SYMBOL,
)
from services.turkiye_fund_snapshot_reader import is_turkiye_fund_production_identity

FUND_REPORT_PAGE = "pages/9_Fund_Report.py"
TRACKED_CONTEXT_KEY = "fund_report_had_tracked_context"

# Display-only official names from accepted KAP identity evidence.
# Local labels — not a live KAP/TEFAS read and not a source of compute.
_NAV_DISPLAY_NAMES = {
    "AIS": "Ak Portföy Para Piyasası Katılım Fonu",
    "ZPE": "Ziraat Portföy Katılım Hisse Senedi Fonu (Hisse Senedi Yoğun Fon)",
    "IAT": "İş Portföy Kira Sertifikaları Katılım (TL) Fonu",
}
_NAV_EXPOSURE_LABELS = {
    "AIS": LAYER_CASH_LIKE,
    "ZPE": "equity",
    "IAT": "sukuk",
}


@dataclass(frozen=True)
class TurkiyeFundNavItem:
    fund_code: str
    instrument: str
    market: str
    official_name: str
    exposure_label: str

    @property
    def identity_label(self) -> str:
        return f"{self.instrument}/{self.market}"


@dataclass(frozen=True)
class FundReportHandoff:
    fund_code: str
    instrument: str
    market: str
    page: str
    session_set: dict[str, Any]
    session_clear: tuple[str, ...]
    query: dict[str, str]
    attach_us_etf_live: bool = False
    invokes_live_analysis: bool = False
    live_refresh: bool = False


def list_turkiye_fund_nav_items() -> tuple[TurkiyeFundNavItem, ...]:
    return tuple(
        TurkiyeFundNavItem(
            fund_code=code,
            instrument=TURKIYE_FUND_8E_INSTRUMENT,
            market=TURKIYE_FUND_8E_MARKET,
            official_name=_NAV_DISPLAY_NAMES[code],
            exposure_label=_NAV_EXPOSURE_LABELS[code],
        )
        for code in PILOT_TEFAS_FUND_CODES
    )


def turkiye_fund_nav_display_name(fund_code: str) -> Optional[str]:
    code = str(fund_code or "").strip().upper()
    return _NAV_DISPLAY_NAMES.get(code)


def is_turkiye_fund_nav_identity(
    symbol: str,
    *,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
) -> bool:
    return is_turkiye_fund_production_identity(
        symbol,
        instrument=instrument,
        market=market,
    )


def us_etf_live_handoff_allowed(
    symbol: str,
    *,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
) -> bool:
    return not is_turkiye_fund_nav_identity(
        symbol,
        instrument=instrument,
        market=market,
    )


def format_turkiye_fund_nav_caption(item: TurkiyeFundNavItem) -> str:
    if item.fund_code == "AIS":
        return (
            f"{item.identity_label} · nakit benzeri ekonomik maruziyet "
            f"· enstrüman {item.instrument}"
        )
    return item.identity_label


def build_turkiye_fund_report_handoff(
    fund_code: str,
    *,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
) -> FundReportHandoff:
    code = str(fund_code or "").strip().upper()
    if not is_turkiye_fund_nav_identity(
        code,
        instrument=instrument,
        market=market,
    ):
        raise ValueError(f"not_turkiye_fund_nav_identity:{fund_code}")
    return FundReportHandoff(
        fund_code=code,
        instrument=TURKIYE_FUND_8E_INSTRUMENT,
        market=TURKIYE_FUND_8E_MARKET,
        page=FUND_REPORT_PAGE,
        session_set={
            FUND_REPORT_SESSION_SYMBOL: code,
            FUND_REPORT_SESSION_INSTRUMENT: TURKIYE_FUND_8E_INSTRUMENT,
            FUND_REPORT_SESSION_MARKET: TURKIYE_FUND_8E_MARKET,
            TRACKED_CONTEXT_KEY: False,
        },
        session_clear=(
            FUND_REPORT_SESSION_LIVE,
            FUND_REPORT_SESSION_RESOLVED,
        ),
        query={
            FUND_REPORT_QUERY_PARAM: code,
            FUND_REPORT_QUERY_INSTRUMENT: TURKIYE_FUND_8E_INSTRUMENT,
            FUND_REPORT_QUERY_MARKET: TURKIYE_FUND_8E_MARKET,
        },
        attach_us_etf_live=False,
        invokes_live_analysis=False,
        live_refresh=False,
    )


def _drop_mapping_key(mapping: MutableMapping[str, Any], key: str) -> None:
    if hasattr(mapping, "pop"):
        try:
            mapping.pop(key, None)
            return
        except TypeError:
            pass
    if key in mapping:
        del mapping[key]


def apply_turkiye_fund_report_handoff(
    session: MutableMapping[str, Any],
    query: MutableMapping[str, Any],
    fund_code: str,
    *,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
) -> FundReportHandoff:
    handoff = build_turkiye_fund_report_handoff(
        fund_code,
        instrument=instrument,
        market=market,
    )
    for key in handoff.session_clear:
        _drop_mapping_key(session, key)
    for key, value in handoff.session_set.items():
        session[key] = value
    for key, value in handoff.query.items():
        query[key] = value
    return handoff


def clear_turkiye_fund_report_identity(
    session: MutableMapping[str, Any],
    query: MutableMapping[str, Any],
) -> None:
    _drop_mapping_key(session, FUND_REPORT_SESSION_INSTRUMENT)
    _drop_mapping_key(session, FUND_REPORT_SESSION_MARKET)
    _drop_mapping_key(query, FUND_REPORT_QUERY_INSTRUMENT)
    _drop_mapping_key(query, FUND_REPORT_QUERY_MARKET)


def discard_us_etf_live_for_turkiye(
    symbol: str,
    *,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
    live_result: Any = None,
    resolved: Any = None,
    analysis_kind: Any = None,
) -> tuple[None, None, None]:
    """Turkish FUND/TR never inherits a US ETF live-analysis session."""
    _ = (symbol, instrument, market, live_result, resolved, analysis_kind)
    if is_turkiye_fund_nav_identity(symbol, instrument=instrument, market=market):
        return None, None, None
    return live_result, resolved, analysis_kind


def nav_item_is_cash_instrument(item: TurkiyeFundNavItem) -> bool:
    """AIS is cash_like exposure, never portfolio CASH / instrument CASH."""
    return False
