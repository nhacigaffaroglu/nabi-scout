from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from services.participation_filter_service import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import EnrichedPositionRow


OPPORTUNITY_LABEL_RESEARCH = "research_opportunity"
OPPORTUNITY_LABEL_DIVERSIFICATION = "diversification_candidate"
OPPORTUNITY_LABEL_ALREADY_HELD = "already_represented"
OPPORTUNITY_LABEL_INSUFFICIENT = "insufficient_evidence"
OPPORTUNITY_LABEL_REVIEW = "participation_review_required"


@dataclass(frozen=True)
class PortfolioOpportunityRow:
    symbol: str
    company_name: str
    sector: Optional[str]
    participation_status: str
    research_status: Optional[str]
    opportunity_label: str
    explanation: str
    nabi_score: Optional[float]


def _held_symbols(rows: Sequence[EnrichedPositionRow]) -> Set[str]:
    return {
        str(row.valuation.symbol or "").upper()
        for row in rows
        if not row.valuation.is_cash and row.valuation.symbol
    }


def _held_sectors(rows: Sequence[EnrichedPositionRow]) -> Set[str]:
    return {
        str(row.sector or "").strip()
        for row in rows
        if not row.valuation.is_cash and row.sector
    }


def build_portfolio_opportunities(
    enriched_positions: Sequence[EnrichedPositionRow],
    candidates: Iterable[Dict[str, object]],
    *,
    limit: int = 12,
) -> Tuple[PortfolioOpportunityRow, ...]:
    held = _held_symbols(enriched_positions)
    held_sectors = _held_sectors(enriched_positions)
    rows: List[PortfolioOpportunityRow] = []

    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        if not symbol or symbol == "CASH":
            continue
        if symbol in held:
            continue

        participation = str(candidate.get("participation_status") or "unknown")
        research_status = candidate.get("research_status")
        sector = candidate.get("sector")
        if isinstance(sector, dict):
            sector = sector.get("name")
        sector_text = str(sector or "").strip() or None
        company_name = str(candidate.get("company_name") or candidate.get("name") or symbol)
        nabi_score = candidate.get("nabi_score")
        if nabi_score is not None:
            nabi_score = float(nabi_score)

        if participation == PARTICIPATION_STATUS_UYGUN_DEGIL:
            label = OPPORTUNITY_LABEL_REVIEW
            explanation = "Katılım durumu uygun değil; portföy fırsat adayı olarak gösterilmez."
            continue
        if participation == PARTICIPATION_STATUS_KONTROL_ET:
            label = OPPORTUNITY_LABEL_REVIEW
            explanation = "Katılım incelemesi gerekli; otomatik öneri yapılmaz."
        elif not research_status or str(research_status).lower() in {"pending", "none", ""}:
            label = OPPORTUNITY_LABEL_INSUFFICIENT
            explanation = "Tamamlanmış NABI araştırması yok."
        elif sector_text and sector_text not in held_sectors:
            label = OPPORTUNITY_LABEL_DIVERSIFICATION
            explanation = (
                f"Portföyde {sector_text} sektörü temsil edilmiyor; "
                f"{symbol} tamamlanmış NABI araştırmasına sahip."
            )
        elif participation == PARTICIPATION_STATUS_UYGUN:
            label = OPPORTUNITY_LABEL_RESEARCH
            explanation = (
                f"{symbol} tamamlanmış NABI araştırmasına ve uygun katılım "
                "durumuna sahip; portföyde temsil edilmiyor."
            )
        else:
            label = OPPORTUNITY_LABEL_INSUFFICIENT
            explanation = "Yeterli kanıt veya katılım durumu net değil."

        rows.append(
            PortfolioOpportunityRow(
                symbol=symbol,
                company_name=company_name,
                sector=sector_text,
                participation_status=participation,
                research_status=str(research_status) if research_status else None,
                opportunity_label=label,
                explanation=explanation,
                nabi_score=nabi_score,
            )
        )

    def _sort_key(row: PortfolioOpportunityRow) -> Tuple[int, float]:
        label_rank = {
            OPPORTUNITY_LABEL_DIVERSIFICATION: 0,
            OPPORTUNITY_LABEL_RESEARCH: 1,
            OPPORTUNITY_LABEL_REVIEW: 2,
            OPPORTUNITY_LABEL_INSUFFICIENT: 3,
            OPPORTUNITY_LABEL_ALREADY_HELD: 4,
        }
        return (label_rank.get(row.opportunity_label, 9), -(row.nabi_score or 0.0))

    rows.sort(key=_sort_key)
    return tuple(rows[:limit])
