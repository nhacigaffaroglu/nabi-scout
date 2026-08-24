from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.scan_repository import ScanRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.watchlist_repository import WatchlistRepository
from services.candidate_surface_service import filter_equity_candidate_surface
from services.daily_brief_service import build_daily_brief
from services.opportunity_center_presentation import build_opportunity_center
from services.nabi_recommendation import (
    build_nabi_recommendation,
    opportunity_intelligence_summary,
)
from services.participation_authority import overlay_candidate_rows
from services.research_monitor_service import build_priority_entries
from services.ui import prepare_protected_page
from components.opportunity_center_ui import render_opportunity_center

client = prepare_protected_page("Fırsatlar | NABI Scout", "🎯")


def _safe_list(loader):
    try:
        return loader()
    except Exception:
        return None


candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
watchlist_repo = WatchlistRepository(client)

candidates = filter_equity_candidate_surface(
    candidate_repo.get_all(order_by="nabi_score", descending=True) or []
)

watch_entries = _safe_list(watchlist_repo.list_active)
priority_by_id = None
if watch_entries:
    try:
        priority_entries = build_priority_entries(
            [item.get("candidate") or {} for item in watch_entries],
            scan_repo=scan_repo,
            watched_candidate_ids=watchlist_repo.watched_candidate_ids(),
        )
        priority_by_id = {
            str(item.get("candidate", {}).get("id")): item
            for item in priority_entries
            if item.get("candidate", {}).get("id")
        }
    except Exception:
        priority_by_id = None

brief = _safe_list(
    lambda: build_daily_brief(
        scan_repo=scan_repo,
        candidate_repo=candidate_repo,
        watchlist_repo=watchlist_repo,
    )
)
expansion_rows = _safe_list(lambda: UniverseExpansionRepository(client).list_all())
snapshots = _safe_list(lambda: ParticipationAssessmentRepository(client).list_latest_by_symbol())
overlaid = overlay_candidate_rows(candidates, snapshots)
recommendation = build_nabi_recommendation(candidates=overlaid)

view = build_opportunity_center(
    candidates=candidates,
    watchlist_entries=watch_entries,
    watchlist_priority=priority_by_id,
    expansion_rows=expansion_rows,
    brief=brief,
    snapshots=snapshots,
    intelligence_summary=opportunity_intelligence_summary(recommendation),
)
render_opportunity_center(view, candidates=candidates)
