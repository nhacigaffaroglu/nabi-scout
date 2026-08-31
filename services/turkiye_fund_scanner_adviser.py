"""Adviser surface for Turkish fund scanner candidates.

Research-only. Rank is not a buy, 8E, or New Money instruction.
"""

from __future__ import annotations

from typing import Any, Optional

from services.official_kap_pdr import _fold
from services.turkiye_fund_scanner import load_default_scanner_result
from services.turkiye_fund_universe_contract import SCANNER_NOT_A_BUY

_SCANNER_TOKENS = (
    "katilim fon",
    "tefas",
    "turkiye fon",
    "fon tarama",
    "participation fund",
    "scanner",
)


def is_turkiye_fund_scanner_question(question: str) -> bool:
    folded = _fold(question)
    return any(token in folded for token in _SCANNER_TOKENS)


def format_scanner_adviser_narrative(result=None) -> str:
    payload = result or load_default_scanner_result()
    lines = [
        "These funds currently rank highest within their peer category based on canonical Fund Intelligence.",
        "Bunlar resmi kanıtı yeterli en yüksek sıralı katılım fonu araştırma adaylarıdır.",
        SCANNER_NOT_A_BUY,
        "Scanner rank is not an 8E decision and not a New Money allocation.",
        "Adviser must not treat scanner rank as a buy instruction.",
    ]
    for category, rows in sorted(payload.ranked_by_category.items()):
        names = ", ".join(f"{row.fund_code} ({row.fi_score})" for row in rows[:3])
        if names:
            lines.append(f"{category}: {names}.")
    if not payload.overall_shortlist:
        lines.append("Şu anda READY araştırma adayı yok; inceleme kuyruğuna bakın.")
    return " ".join(lines)


def scanner_adviser_facts(result=None) -> dict[str, Any]:
    payload = result or load_default_scanner_result()
    return {
        "role": "research_candidates_only",
        "not_a_buy": True,
        "not_eight_e": True,
        "not_new_money": True,
        "discovered_count": payload.discovered_count,
        "scanner_ready_count": payload.scanner_ready_count,
        "shortlist": [
            {
                "fund_code": row.fund_code,
                "category": row.category,
                "fi_score": row.fi_score,
                "fi_state": row.fi_state,
                "rank": row.rank,
                "status": row.scanner_status,
            }
            for row in payload.overall_shortlist
        ],
        "disclaimer": SCANNER_NOT_A_BUY,
    }


def turkiye_fund_scanner_adviser_overlay(question: str) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    if not is_turkiye_fund_scanner_question(question):
        return None, None
    result = load_default_scanner_result()
    return format_scanner_adviser_narrative(result), scanner_adviser_facts(result)
