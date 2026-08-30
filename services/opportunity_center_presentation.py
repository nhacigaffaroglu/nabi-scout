"""Fırsatlar Opportunity Center composition. No scoring engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from services.candidate_pipeline_presentation import (
    ACTIONABLE_DECISIONS,
    INCOMPLETE_DECISIONS,
    NO_OPPORTUNITY_COPY,
    STAGE_DISCOVERED,
    STAGE_FULLY_EVALUATED,
    STAGE_ONBOARDING,
    STAGE_PARTICIPATION_CHECKED,
    STAGE_RESEARCH_PENDING,
    STAGE_SCANNED,
    analysis_is_incomplete,
    classify_candidate_pipeline_stage,
    display_nabi_score,
    has_valid_current_price,
    is_actionable_opportunity,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.research_monitor_service import summarize_change
from services.participation_authority import (
    is_approved_open_research,
    overlay_candidate_rows,
)
from services.research_workflow_service import (
    normalize_research_status,
)
from services.nabi_portfolio_fit import fit_label_tr
from services.research_intelligence_contract import ResearchIntelligenceBrief
from services.nabi_decision_contract import DecisionV3Brief
from services.nabi_recommendation_history_presentation import TRACKING_READY
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityDecision,
)
from services.wealth_contract import normalize_symbol
from services.research_intelligence_service import (
    build_research_intelligence,
    present_research_intelligence_brief,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_BLOCKED,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_EXHAUSTED,
    EXPANSION_STATUS_IN_PROGRESS,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)

CENTER_TITLE = "Fırsatlar"
CENTER_CAPTION = "Yeni yatırım fırsatları ve hangilerini araştırman gerektiği."
TODAY_TITLE = "NABI — Bugünkü Fırsatlar"
RESEARCH_TITLE = "Araştırma Kuyruğu"
WATCHLIST_TITLE = "İzlediklerim"
DISCOVERY_TITLE = "Yeni Keşifler"
ADVANCED_TITLE = "Gelişmiş Araçlar"
ALL_CANDIDATES_LABEL = "Tüm adayları göster"
ALL_RESEARCH_LABEL = "Tüm araştırmaları göster"
ALL_WATCHLIST_LABEL = "Tüm izleme listesini göster"
INSPECT_LABEL = "Şirketi İncele"
FIRSATLARI_GOR_LABEL = "Fırsatları Gör"
OTHER_OPPORTUNITIES_LABEL = "Diğer uygun fırsatlar"
COMPANY_REPORT_PAGE = "pages/4_Company_Report.py"
FIRSATLAR_PAGE = "pages/5_Firsatlar.py"
RESEARCH_PAGE = "pages/3_Research_Monitor.py"
WATCHLIST_PAGE = "pages/6_Izleme_Listesi.py"
CANDIDATE_POOL_PAGE = "pages/2_Aday_Havuzu.py"
UNIVERSE_PAGE = "pages/2_Evren_Motoru.py"
SCANNER_PAGE = "pages/2_Scout_Tarama.py"

KPI_STRONG = "Güçlü Fırsatlar"
KPI_RESEARCH = "Araştırılacaklar"
KPI_WATCHLIST = "İzlediklerim"
KPI_DISCOVERED = "Yeni Keşfedilenler"

PRIMARY_NAV_LABELS = ("Dashboard", "Wealth", "Fırsatlar")
HIDDEN_PRIMARY_LABELS = (
    "Aday Havuzu",
    "Evren Motoru",
    "Scout Tarama",
    "Research Monitor",
    "Company Report",
    "İzleme Listesi",
)

MAX_TODAY_OPPORTUNITIES = 3
MAX_RESEARCH_ITEMS = 3
MAX_WATCHLIST_ITEMS = 3
MAX_DISCOVERY_ITEMS = 5

USER_STAGE_LABELS = {
    STAGE_DISCOVERED: "Yeni keşfedildi",
    STAGE_ONBOARDING: "Değerlendirme bekliyor",
    STAGE_PARTICIPATION_CHECKED: "Katılım uygunluğu kontrol edildi",
    STAGE_SCANNED: "İnceleniyor",
    STAGE_RESEARCH_PENDING: "Araştırma bekliyor",
    STAGE_FULLY_EVALUATED: "Değerlendirme tamamlandı",
}

DISCOVERY_NEW = "Yeni keşfedildi"
DISCOVERY_WAITING = "Değerlendirme bekleyenler"
DISCOVERY_DONE = "Değerlendirme tamamlandı"
DISCOVERY_FAILED = "Değerlendirme tamamlanamadı"

NO_WATCHLIST_CHANGE_COPY = "İzleme listesinde dikkat gerektiren bir değişiklik yok."
NO_RESEARCH_COPY = "Şu anda öne çıkan bir araştırma maddesi yok."
NO_DISCOVERY_COPY = "Yeni keşif bekleyen şirket yok."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decision(candidate: Mapping[str, Any]) -> str:
    return _text(candidate.get("decision") or candidate.get("decision_label"))


def participation_user_label(candidate: Mapping[str, Any]) -> str:
    status = _text(candidate.get("participation_status"))
    if status == PARTICIPATION_STATUS_UYGUN:
        return "Katılım uygunluğu kontrol edildi"
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return "Katılım uygun değil"
    if (not status) or status == PARTICIPATION_STATUS_KONTROL_ET:
        return "Katılım uygunluğu kontrol ediliyor"
    return status


def evaluation_user_label(candidate: Mapping[str, Any]) -> str:
    if _decision(candidate) in INCOMPLETE_DECISIONS:
        return "Veri eksik"
    stage = classify_candidate_pipeline_stage(candidate)
    return USER_STAGE_LABELS.get(stage, "İnceleniyor")


def format_current_price(candidate: Mapping[str, Any]) -> Optional[str]:
    if not has_valid_current_price(candidate):
        return None
    try:
        price = float(candidate.get("current_price"))
    except (TypeError, ValueError):
        return None
    currency = _text(candidate.get("currency"))
    formatted = f"{price:,.2f}"
    return f"{formatted} {currency}".strip() if currency else formatted


def opportunity_teaser_copy(*, strong_count: int, qualified_count: int, empty_copy: str) -> str:
    if strong_count > 0:
        return f"{strong_count} güçlü yatırım fırsatı var."
    if qualified_count > 0:
        return f"{qualified_count} araştırılacak aday var."
    return empty_copy


@dataclass(frozen=True)
class OpportunityHeroKpi:
    label: str
    value: str


@dataclass(frozen=True)
class TodayOpportunityCard:
    symbol: str
    company_name: str
    decision: str
    nabi_score: Optional[float]
    participation_label: str
    why: Optional[str]
    risk: Optional[str]
    price_label: Optional[str]
    research_brief: Optional[ResearchIntelligenceBrief] = None


@dataclass(frozen=True)
class OpportunityComparisonCard:
    symbol: str
    decision: str
    nabi_score: Optional[float]
    fit_label: str
    strength: Optional[str]
    risk: Optional[str]
    rank_reason: str
    rank: int
    research_brief: Optional[ResearchIntelligenceBrief] = None


@dataclass(frozen=True)
class ResearchQueueItem:
    symbol: str
    company_name: str
    summary: str
    exceptional: bool


@dataclass(frozen=True)
class WatchlistAttentionItem:
    symbol: str
    company_name: str
    change: str
    decision: Optional[str]


@dataclass(frozen=True)
class DiscoveryItem:
    symbol: str
    status_label: str


@dataclass(frozen=True)
class OpportunityHero:
    kpis: tuple[OpportunityHeroKpi, ...]
    recommendation: str


@dataclass(frozen=True)
class ResearchSummary:
    waiting_count: Optional[int]
    completed_count: Optional[int]
    incomplete_count: Optional[int]
    headline: Optional[str]
    items: tuple[ResearchQueueItem, ...]
    empty_copy: str


@dataclass(frozen=True)
class WatchlistSummary:
    available: bool
    count: Optional[int]
    items: tuple[WatchlistAttentionItem, ...]
    empty_copy: str


@dataclass(frozen=True)
class DiscoverySummary:
    available: bool
    new_count: Optional[int]
    waiting_count: Optional[int]
    items: tuple[DiscoveryItem, ...]
    empty_copy: str


@dataclass(frozen=True)
class OpportunityCenterView:
    title: str
    caption: str
    hero: OpportunityHero
    today: tuple[TodayOpportunityCard, ...]
    today_empty: str
    research: ResearchSummary
    watchlist: WatchlistSummary
    discoveries: DiscoverySummary
    comparison_cards: tuple[OpportunityComparisonCard, ...] = ()
    comparison_note: Optional[str] = None
    other_opportunities: tuple[TodayOpportunityCard, ...] = ()
    decision_brief: Optional[DecisionV3Brief] = None
    tracking_status: Optional[str] = None
    history_lines: tuple[str, ...] = ()
    security_decisions: tuple[PortfolioSecurityDecision, ...] = ()


def opportunity_security_action(
    view: OpportunityCenterView,
    symbol: Optional[str] = None,
) -> Optional[PortfolioSecurityDecision]:
    """Canonical 8E action displayed by Fırsatlar. Never a v3/Recommendation action."""
    needle = normalize_symbol(symbol)
    if not needle and view.today:
        needle = normalize_symbol(view.today[0].symbol)
    if needle:
        for item in view.security_decisions:
            if item.symbol == needle:
                return item
    if view.security_decisions:
        return view.security_decisions[0]
    return None


def opportunity_displayed_security_action(
    view: OpportunityCenterView,
    symbol: Optional[str] = None,
) -> str:
    action = opportunity_security_action(view, symbol)
    if action is not None:
        return action.decision
    return DECISION_INSUFFICIENT_DATA


def _why(candidate: Mapping[str, Any]) -> Optional[str]:
    return (
        _text(candidate.get("main_reason") or candidate.get("investment_thesis"))
        or None
    )


def _risk(candidate: Mapping[str, Any]) -> Optional[str]:
    return _text(candidate.get("critical_risk")) or None


def select_today_opportunity_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_TODAY_OPPORTUNITIES,
) -> tuple[Mapping[str, Any], ...]:
    qualified = [
        row
        for row in candidates
        if is_actionable_opportunity(row) and _decision(row) in ACTIONABLE_DECISIONS
    ]

    def _rank(row: Mapping[str, Any]) -> tuple[int, float, str]:
        score = display_nabi_score(row)
        rank_score = score if score is not None else -1.0
        strong = 0 if _decision(row) == "GÜÇLÜ ADAY" else 1
        return (strong, -rank_score, _text(row.get("symbol")).upper())

    qualified.sort(key=_rank)
    return tuple(qualified[: max(0, limit)])


def _research_brief_for_candidate(
    candidate: Optional[Mapping[str, Any]],
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
) -> Optional[ResearchIntelligenceBrief]:
    if not candidate:
        return None
    view = build_research_intelligence(candidate=candidate, snapshot=snapshot)
    return present_research_intelligence_brief(view)


def present_today_opportunity_cards(
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_TODAY_OPPORTUNITIES,
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[TodayOpportunityCard, ...]:
    cards: list[TodayOpportunityCard] = []
    by_snapshot = snapshots or {}
    for candidate in select_today_opportunity_candidates(candidates, limit=limit):
        symbol = _text(candidate.get("symbol")).upper()
        cards.append(
            TodayOpportunityCard(
                symbol=symbol,
                company_name=_text(candidate.get("company_name")) or symbol,
                decision=_decision(candidate),
                nabi_score=display_nabi_score(candidate),
                participation_label=participation_user_label(candidate),
                why=_why(candidate),
                risk=_risk(candidate),
                price_label=format_current_price(candidate),
                research_brief=_research_brief_for_candidate(
                    candidate,
                    snapshot=by_snapshot.get(symbol),
                ),
            )
        )
    return tuple(cards)


def count_strong_opportunities(candidates: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in candidates
        if is_actionable_opportunity(row) and _decision(row) == "GÜÇLÜ ADAY"
    )


def count_research_waiting(candidates: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in candidates if is_approved_open_research(row))


def count_research_completed(candidates: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in candidates
        if normalize_research_status(row.get("research_status")) == "TAMAMLANDI"
    )


def count_research_incomplete(candidates: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in candidates if analysis_is_incomplete(row))


def present_research_summary(
    candidates: Sequence[Mapping[str, Any]],
    brief: Optional[Mapping[str, Any]] = None,
    *,
    limit: int = MAX_RESEARCH_ITEMS,
) -> ResearchSummary:
    waiting = count_research_waiting(candidates)
    completed = count_research_completed(candidates)
    incomplete = count_research_incomplete(candidates)
    parts = [
        f"{waiting} şirket araştırma bekliyor",
        f"{completed} şirketin araştırması tamamlandı",
    ]
    if incomplete:
        parts.append(f"{incomplete} şirkette veri eksik")
    headline = " · ".join(parts)

    items: list[ResearchQueueItem] = []
    if brief:
        for raw in list(brief.get("today_actions") or []):
            symbol = _text(raw.get("symbol")).upper()
            if not symbol:
                continue
            items.append(
                ResearchQueueItem(
                    symbol=symbol,
                    company_name=_text(raw.get("company_name")) or symbol,
                    summary=_text(raw.get("action_label") or raw.get("next_action"))
                    or "Araştırma bekliyor",
                    exceptional=False,
                )
            )
        for raw in list(brief.get("data_quality_updates") or []):
            symbol = _text(raw.get("symbol")).upper()
            if not symbol:
                continue
            items.append(
                ResearchQueueItem(
                    symbol=symbol,
                    company_name=_text(raw.get("company_name")) or symbol,
                    summary=_text(raw.get("summary")) or "Veri eksik",
                    exceptional=True,
                )
            )
    return ResearchSummary(
        waiting_count=waiting,
        completed_count=completed,
        incomplete_count=incomplete,
        headline=headline,
        items=tuple(items[: max(0, limit)]),
        empty_copy=NO_RESEARCH_COPY,
    )


def _watchlist_change_is_notable(change: str) -> bool:
    text = (change or "").casefold()
    return text not in {
        "anlamlı değişiklik yok",
        "önceki tarama bulunamadı",
    }


def present_watchlist_summary(
    entries: Optional[Sequence[Mapping[str, Any]]],
    priority_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    limit: int = MAX_WATCHLIST_ITEMS,
) -> WatchlistSummary:
    if entries is None:
        return WatchlistSummary(
            available=False,
            count=None,
            items=(),
            empty_copy=NO_WATCHLIST_CHANGE_COPY,
        )
    items: list[WatchlistAttentionItem] = []
    lookup = priority_by_id or {}
    for item in entries:
        candidate = item.get("candidate") or {}
        symbol = _text(candidate.get("symbol")).upper()
        if not symbol:
            continue
        candidate_id = _text(item.get("candidate_id") or candidate.get("id"))
        recent = (lookup.get(candidate_id) or {}).get("recent_change")
        change = summarize_change(recent)
        if not _watchlist_change_is_notable(change):
            continue
        decision = _decision(candidate) or None
        if decision and decision not in ACTIONABLE_DECISIONS and decision not in INCOMPLETE_DECISIONS:
            decision = None
        items.append(
            WatchlistAttentionItem(
                symbol=symbol,
                company_name=_text(candidate.get("company_name")) or symbol,
                change=change,
                decision=decision if decision in ACTIONABLE_DECISIONS else None,
            )
        )
    return WatchlistSummary(
        available=True,
        count=len(list(entries)),
        items=tuple(items[: max(0, limit)]),
        empty_copy=NO_WATCHLIST_CHANGE_COPY,
    )


def discovery_user_label(status: Any, participation_status: Any = None) -> str:
    participation = _text(participation_status)
    if participation == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return DISCOVERY_FAILED
    value = _text(status).upper()
    if value == EXPANSION_STATUS_PENDING:
        return DISCOVERY_NEW
    if value in {EXPANSION_STATUS_IN_PROGRESS, EXPANSION_STATUS_RETRYABLE}:
        return DISCOVERY_WAITING
    if value == EXPANSION_STATUS_COMPLETED:
        return DISCOVERY_DONE
    if value in {EXPANSION_STATUS_BLOCKED, EXPANSION_STATUS_EXHAUSTED}:
        return DISCOVERY_FAILED
    return DISCOVERY_WAITING


def present_discovery_summary(
    queue_rows: Optional[Sequence[Mapping[str, Any]]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_DISCOVERY_ITEMS,
) -> DiscoverySummary:
    pipeline_new = [
        row
        for row in candidates
        if classify_candidate_pipeline_stage(row) in {STAGE_DISCOVERED, STAGE_ONBOARDING}
    ]
    if queue_rows is None and not pipeline_new:
        return DiscoverySummary(
            available=False,
            new_count=None,
            waiting_count=None,
            items=(),
            empty_copy=NO_DISCOVERY_COPY,
        )

    items: list[DiscoveryItem] = []
    new_count = 0
    waiting_count = 0
    if queue_rows is not None:
        for row in queue_rows:
            label = discovery_user_label(
                row.get("status"),
                row.get("participation_status"),
            )
            if label == DISCOVERY_NEW:
                new_count += 1
            elif label == DISCOVERY_WAITING:
                waiting_count += 1
            if label not in {DISCOVERY_NEW, DISCOVERY_WAITING}:
                continue
            symbol = _text(row.get("symbol")).upper()
            if not symbol:
                continue
            items.append(DiscoveryItem(symbol=symbol, status_label=label))
    else:
        new_count = len(pipeline_new)
        waiting_count = new_count
        for row in pipeline_new:
            symbol = _text(row.get("symbol")).upper()
            if not symbol:
                continue
            items.append(
                DiscoveryItem(
                    symbol=symbol,
                    status_label=evaluation_user_label(row),
                )
            )
    return DiscoverySummary(
        available=True,
        new_count=new_count,
        waiting_count=waiting_count,
        items=tuple(items[: max(0, limit)]),
        empty_copy=NO_DISCOVERY_COPY,
    )


def present_comparison_cards(
    comparisons: Sequence[Any] = (),
    *,
    limit: int = MAX_TODAY_OPPORTUNITIES,
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[OpportunityComparisonCard, ...]:
    cards: list[OpportunityComparisonCard] = []
    by_symbol = {
        _text(row.get("symbol")).upper(): row
        for row in candidates
        if _text(row.get("symbol"))
    }
    by_snapshot = snapshots or {}
    for item in list(comparisons)[: max(0, limit)]:
        strengths = tuple(getattr(item, "strengths", ()) or ())
        risks = tuple(getattr(item, "risks", ()) or ())
        symbol = _text(getattr(item, "symbol", "")).upper()
        cards.append(
            OpportunityComparisonCard(
                symbol=symbol,
                decision=_text(getattr(item, "decision_class", None)),
                nabi_score=getattr(item, "nabi_score", None),
                fit_label=fit_label_tr(getattr(item, "portfolio_fit", "")),
                strength=strengths[0] if strengths else None,
                risk=risks[0] if risks else None,
                rank_reason=_text(getattr(item, "rank_reason", None)),
                rank=int(getattr(item, "rank", len(cards) + 1) or len(cards) + 1),
                research_brief=_research_brief_for_candidate(
                    by_symbol.get(symbol),
                    snapshot=by_snapshot.get(symbol),
                ),
            )
        )
    return tuple(cards)


def present_hero(
    *,
    candidates: Sequence[Mapping[str, Any]],
    today: Sequence[TodayOpportunityCard],
    watchlist: WatchlistSummary,
    discoveries: DiscoverySummary,
    intelligence_summary: Optional[str] = None,
) -> OpportunityHero:
    kpis: list[OpportunityHeroKpi] = []
    strong = count_strong_opportunities(candidates)
    kpis.append(OpportunityHeroKpi(KPI_STRONG, str(strong)))
    kpis.append(OpportunityHeroKpi(KPI_RESEARCH, str(count_research_waiting(candidates))))
    if watchlist.available and watchlist.count is not None:
        kpis.append(OpportunityHeroKpi(KPI_WATCHLIST, str(watchlist.count)))
    if discoveries.available and discoveries.new_count is not None:
        kpis.append(OpportunityHeroKpi(KPI_DISCOVERED, str(discoveries.new_count)))

    if intelligence_summary:
        recommendation = intelligence_summary
    elif today:
        names = ", ".join(card.symbol for card in today[:MAX_TODAY_OPPORTUNITIES])
        recommendation = f"NABI bugün {names} fırsatına bakmanı öneriyor."
    else:
        recommendation = NO_OPPORTUNITY_COPY
    return OpportunityHero(kpis=tuple(kpis), recommendation=recommendation)


def build_opportunity_center(
    *,
    candidates: Sequence[Mapping[str, Any]],
    watchlist_entries: Optional[Sequence[Mapping[str, Any]]] = None,
    watchlist_priority: Optional[Mapping[str, Mapping[str, Any]]] = None,
    expansion_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    brief: Optional[Mapping[str, Any]] = None,
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    intelligence_summary: Optional[str] = None,
    comparisons: Sequence[Any] = (),
    comparison_note: Optional[str] = None,
    decision_brief: Optional[DecisionV3Brief] = None,
    tracking_status: Optional[str] = None,
    history_lines: tuple[str, ...] = (),
    security_decisions: Sequence[PortfolioSecurityDecision] = (),
) -> OpportunityCenterView:
    candidates = overlay_candidate_rows(candidates, snapshots)
    today = present_today_opportunity_cards(candidates, snapshots=snapshots)
    research = present_research_summary(candidates, brief)
    watchlist = present_watchlist_summary(watchlist_entries, watchlist_priority)
    discoveries = present_discovery_summary(expansion_rows, candidates)
    comparison_cards = present_comparison_cards(
        comparisons,
        candidates=candidates,
        snapshots=snapshots,
    )
    compared = {card.symbol for card in comparison_cards}
    other = tuple(card for card in today if card.symbol not in compared)
    hero = present_hero(
        candidates=candidates,
        today=today,
        watchlist=watchlist,
        discoveries=discoveries,
        intelligence_summary=intelligence_summary,
    )
    return OpportunityCenterView(
        title=CENTER_TITLE,
        caption=CENTER_CAPTION,
        hero=hero,
        today=today,
        today_empty=NO_OPPORTUNITY_COPY,
        research=research,
        watchlist=watchlist,
        discoveries=discoveries,
        comparison_cards=comparison_cards,
        comparison_note=comparison_note,
        other_opportunities=other,
        decision_brief=decision_brief,
        tracking_status=tracking_status if tracking_status is not None else TRACKING_READY,
        history_lines=history_lines,
        security_decisions=tuple(security_decisions),
    )
