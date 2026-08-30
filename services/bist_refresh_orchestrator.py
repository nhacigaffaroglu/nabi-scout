"""Change-driven BIST Facts → SI → snapshot orchestration.

Scheduler owns sequencing. Canonical services own calculations.
Does not run New Money or mutate portfolios.
Default is dry-run with persist_si and persist_participation off.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from services.bist_corporate_action_audit import (
    STATUS_UNRESOLVED,
    events_from_thb_flags,
    merge_official_events,
    window_adjustment_status,
)
from services.bist_official_market_facts import (
    attach_official_nominal_market_cap,
    market_facts_from_thb_bulletin,
)
from services.bist_official_participation_policy import official_decision_compare_key
from services.bist_refresh_contract import (
    CHANGE_CAPITAL,
    CHANGE_CORPORATE_ACTION,
    CHANGE_FINANCIAL_FACTS,
    CHANGE_PARTICIPATION,
    CHANGE_PRICE_HISTORY,
    JOB_NAME,
    MAX_SYMBOLS_DEFAULT,
    REASON_BROAD_UNIVERSE,
    REASON_DRY_RUN,
    REASON_FIXTURE_MOMENTUM,
    REASON_NO_CHANGE,
    REASON_PERSIST_DISABLED,
    REASON_QUALITY_GATE,
    REASON_SOURCE_FAILURE_PRESERVE,
    REASON_UNRESOLVED_CA,
    REASON_US_ISOLATED,
    STATUS_BLOCKED,
    STATUS_CHECKED,
    STATUS_CORRECTION,
    STATUS_NEW_PERIOD,
    STATUS_NO_CHANGE,
    STATUS_RESTATEMENT,
    STATUS_SKIPPED,
    STATUS_SOURCE_FAILURE,
    STATUS_SOURCE_UNAVAILABLE,
    STATUS_UNRESOLVED_CA,
    STATUS_US_ISOLATED,
    STATUS_WOULD_PUBLISH,
    BistRefreshRun,
    BistRefreshState,
    BistSymbolRefresh,
)
from services.bist_symbol_mapping import BIST_EXCHANGES
from services.bist_thb_history import (
    SOURCE_THB_HISTORY,
    last_cached_ok_date,
    load_cached_bulletin,
    load_cached_series,
    load_history_cache,
    missing_weekday_dates,
)
from services.kap_annual_history import (
    build_kap_annual_history,
    kap_security_facts_payload_from_history,
)
from services.kap_capital_structure import parse_kap_capital_structure_html
from services.kap_kafif_contract import KapKafifDiscovery
from services.kap_public_contract import KapFrDiscovery, KapPublicFinancialDocument
from services.kap_public_fr_discovery import incremental_annual_targets
from services.participation_assessment_persistence_service import (
    official_participation_source_unavailable,
    publish_official_bist_participation,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import SecurityParticipationContext
from services.security_intelligence_publish import publish_canonical_security_intelligence
from services.security_master_contract import INSTRUMENT_EQUITY, SOURCE_BIST
from services.security_master_service import SecurityMasterService
from services.signal_ingestion_universe import TR_MARKETS
from services.wealth_contract import normalize_symbol


FIXTURE_WEEKDAY_OBSERVED_AT = "2026-08-30T00:00:00+00:00"
FORBIDDEN_SOURCE_MARKERS = ("weekday_series", "FIXTURE_WEEKDAY", "synthetic Momentum")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def fixture_momentum_forbidden(series: Sequence[Any]) -> bool:
    """Refuse test-only weekday_series rows on the production refresh path."""
    if not series:
        return False
    observed = {getattr(row, "observed_at", "") for row in series}
    sources = {getattr(row, "source", "") for row in series}
    if observed == {FIXTURE_WEEKDAY_OBSERVED_AT} and SOURCE_THB_HISTORY in sources:
        closes = [getattr(row, "close", None) for row in series[:5]]
        if len(closes) >= 3 and all(item is not None for item in closes):
            steps = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
            if steps and all(abs(step - steps[0]) < 1e-9 for step in steps):
                return True
    return False


def kafif_is_newer(
    previous_id: str,
    previous_submitted: str,
    current: Optional[KapKafifDiscovery],
) -> bool:
    if current is None:
        return False
    if current.disclosure_id != previous_id:
        return True
    if current.submitted_at and previous_submitted and current.submitted_at != previous_submitted:
        return True
    return False


def _json_key(evidence: Any) -> str:
    if evidence is None:
        return ""
    payload = official_decision_compare_key(evidence)
    return "|".join(str(payload.get(key) or "") for key in payload)


def _membership_key(membership: Any) -> str:
    if membership is None:
        return ""
    member = getattr(membership, "member", None)
    as_of = getattr(member, "as_of", "") if member is not None else ""
    return "|".join(
        (
            str(getattr(membership, "status", "") or ""),
            str(getattr(membership, "membership", "")),
            str(as_of or ""),
        )
    )


def _us_isolated(symbol: str, master: Optional[SecurityMasterService]) -> bool:
    if master is None:
        return False
    try:
        resolution = master.resolve_security(symbol)
    except Exception:
        return False
    source = str(getattr(resolution, "source", "") or "")
    if source == SOURCE_BIST:
        return False
    facts = getattr(resolution, "facts", ()) or ()
    exchange = str(getattr(facts[0], "exchange", "") if facts else "").upper()
    if exchange in BIST_EXCHANGES or exchange in TR_MARKETS:
        return False
    instrument = str(getattr(resolution, "instrument_type", "") or "")
    if source and source != SOURCE_BIST and instrument == INSTRUMENT_EQUITY:
        return True
    return False


def compose_official_facts(
    symbol: str,
    *,
    documents: Sequence[KapPublicFinancialDocument] = (),
    bulletin: Any = None,
    series: Sequence[Any] = (),
    capital_html: str = "",
    official_events: Sequence[Any] = (),
):
    if fixture_momentum_forbidden(series):
        raise ValueError(REASON_FIXTURE_MOMENTUM)
    history = build_kap_annual_history(symbol, documents) if documents else None
    payload = kap_security_facts_payload_from_history(history) if history is not None else None
    market = None
    if bulletin is not None:
        try:
            market = market_facts_from_thb_bulletin(bulletin, symbol)
        except ValueError:
            market = None
    if market is not None and capital_html:
        market = attach_official_nominal_market_cap(
            market,
            parse_kap_capital_structure_html(
                capital_html,
                symbol=symbol,
                source_url=f"https://kap.org.tr/tr/sirket-bilgileri/genel/{symbol}",
            ),
        )
    flags = events_from_thb_flags(series)
    events = merge_official_events(official_events, flags)
    return SecurityFactsService().build(
        symbol,
        kap_financials=payload,
        bist_market_facts=market,
        bist_price_history=series,
        bist_corporate_actions=events,
        allow_sec_cache_replay=False,
    ), history, events


def run_bist_refresh(
    symbols: Sequence[str],
    *,
    dry_run: bool = True,
    persist_si: bool = False,
    persist_participation: bool = False,
    allow_live: bool = False,
    allow_broad: bool = False,
    as_of: Optional[date] = None,
    state: Optional[BistRefreshState] = None,
    kap_discoveries: Mapping[str, Sequence[KapFrDiscovery]] = (),
    kap_documents: Mapping[str, Sequence[KapPublicFinancialDocument]] = (),
    kafif_discoveries: Mapping[str, Sequence[KapKafifDiscovery]] = (),
    participation_status: Mapping[str, str] = (),
    participation_evidence: Mapping[str, Any] = (),
    capital_html: Mapping[str, str] = (),
    capital_versions: Mapping[str, str] = (),
    official_events: Mapping[str, Sequence[Any]] = (),
    thb_cache: Any = None,
    source_failures: Mapping[str, str] = (),
    snapshot_repo: Any = None,
    participation_repo: Any = None,
    memberships: Mapping[str, Any] = (),
    kafif_documents: Mapping[str, Any] = (),
    security_master: Optional[SecurityMasterService] = None,
    max_symbols: int = MAX_SYMBOLS_DEFAULT,
) -> BistRefreshRun:
    """Refresh affected BIST securities. Default writes nothing."""
    started = _now()
    run_id = str(uuid4())
    as_of = as_of or date.today()
    prior = state or BistRefreshState()
    kap_discoveries = dict(kap_discoveries or {})
    kap_documents = dict(kap_documents or {})
    kafif_discoveries = dict(kafif_discoveries or {})
    participation_status = dict(participation_status or {})
    participation_evidence = dict(participation_evidence or {})
    capital_html = dict(capital_html or {})
    capital_versions = dict(capital_versions or {})
    official_events = dict(official_events or {})
    source_failures = dict(source_failures or {})
    memberships = dict(memberships or {})
    kafif_documents = dict(kafif_documents or {})
    requested = [normalize_symbol(item) for item in symbols if normalize_symbol(item)]
    errors: list[str] = []
    if len(requested) > max_symbols and not allow_broad:
        return BistRefreshRun(
            run_id=run_id,
            started_at=started,
            finished_at=_now(),
            status="refused",
            dry_run=dry_run,
            persist_si=False,
            persist_participation=False,
            symbols_checked=len(requested),
            errors=(REASON_BROAD_UNIVERSE,),
            next_state=prior,
        )
    if allow_live and not persist_si:
        allow_live = bool(allow_live)
    cache = thb_cache if thb_cache is not None else load_history_cache()
    latest_thb = last_cached_ok_date(cache)
    missing = missing_weekday_dates(cache, as_of=as_of)
    if allow_live:
        errors.append("LIVE_FETCH_NOT_ENABLED_THIS_SPRINT")
    master = security_master if security_master is not None else SecurityMasterService()
    results: list[BistSymbolRefresh] = []
    known_ids = set(prior.known_ids())
    next_kafif: list[tuple[str, str]] = list(prior.latest_kafif_ids)
    next_kafif_sub: list[tuple[str, str]] = list(prior.latest_kafif_submitted)
    next_part: list[tuple[str, str]] = list(prior.participation_keys)
    next_membership: list[tuple[str, str]] = list(prior.membership_keys)
    next_cap: list[tuple[str, str]] = list(prior.capital_versions)
    published = 0
    processed = 0
    skipped = 0
    changes_n = 0
    part_changes = 0
    part_processed = 0
    part_published = 0
    part_skipped = 0
    part_errors: list[str] = []

    for symbol in requested:
        if _us_isolated(symbol, master):
            skipped += 1
            results.append(
                BistSymbolRefresh(
                    symbol=symbol,
                    kap_status=STATUS_US_ISOLATED,
                    reason=REASON_US_ISOLATED,
                )
            )
            continue
        failure = source_failures.get(symbol)
        if failure:
            skipped += 1
            results.append(
                BistSymbolRefresh(
                    symbol=symbol,
                    kap_status=STATUS_SOURCE_FAILURE,
                    thb_status=STATUS_SOURCE_FAILURE if failure == "THB" else STATUS_CHECKED,
                    kafif_status=STATUS_SOURCE_FAILURE if failure == "KAFIF" else STATUS_CHECKED,
                    facts_status=STATUS_SKIPPED,
                    si_status=STATUS_SKIPPED,
                    would_publish=False,
                    reason=REASON_SOURCE_FAILURE_PRESERVE,
                    error=failure,
                    latest_thb_date=_iso(latest_thb),
                )
            )
            continue
        try:
            row = _refresh_symbol(
                symbol,
                as_of=as_of,
                prior=prior,
                cache=cache,
                latest_thb=latest_thb,
                missing=missing,
                discoveries=tuple(kap_discoveries.get(symbol, ()) or ()),
                documents=tuple(kap_documents.get(symbol, ()) or ()),
                kafif_rows=tuple(kafif_discoveries.get(symbol, ()) or ()),
                participation=participation_status.get(symbol, PARTICIPATION_STATUS_UYGUN),
                evidence=participation_evidence.get(symbol),
                capital=capital_html.get(symbol, ""),
                capital_version=capital_versions.get(symbol, ""),
                events=tuple(official_events.get(symbol, ()) or ()),
                dry_run=dry_run,
                persist_si=persist_si,
                persist_participation=persist_participation,
                snapshot_repo=snapshot_repo,
                participation_repo=participation_repo,
                membership=memberships.get(symbol),
                kafif_document=kafif_documents.get(symbol),
            )
        except Exception as exc:
            skipped += 1
            errors.append(f"{symbol}:{type(exc).__name__}")
            results.append(
                BistSymbolRefresh(
                    symbol=symbol,
                    facts_status=STATUS_SOURCE_FAILURE,
                    reason=REASON_SOURCE_FAILURE_PRESERVE,
                    error=type(exc).__name__,
                )
            )
            continue
        results.append(row)
        if row.changes:
            changes_n += 1
            processed += 1
        else:
            skipped += 1
        if CHANGE_PARTICIPATION in row.changes:
            part_changes += 1
            part_processed += 1
        if row.participation_published:
            part_published += 1
        elif row.participation_skipped:
            part_skipped += 1
        if row.error and CHANGE_PARTICIPATION in row.changes:
            part_errors.append(f"{row.symbol}:{row.error}")
        if row.published:
            published += 1
        known_ids.update(row.latest_notification_ids)
        if row.latest_kafif_id:
            next_kafif = [(key, value) for key, value in next_kafif if key != symbol]
            next_kafif.append((symbol, row.latest_kafif_id))
        submitted = ""
        current_kafif = _latest_kafif(kafif_discoveries.get(symbol, ()))
        if current_kafif is not None:
            submitted = current_kafif.submitted_at
            next_kafif_sub = [(key, value) for key, value in next_kafif_sub if key != symbol]
            next_kafif_sub.append((symbol, submitted))
        if row.symbol:
            key = _json_key(participation_evidence.get(symbol))
            if key:
                next_part = [(item, value) for item, value in next_part if item != symbol]
                next_part.append((symbol, key))
            mem_key = _membership_key(memberships.get(symbol))
            if mem_key:
                next_membership = [
                    (item, value) for item, value in next_membership if item != symbol
                ]
                next_membership.append((symbol, mem_key))
        version = capital_versions.get(symbol, "")
        if version:
            next_cap = [(item, value) for item, value in next_cap if item != symbol]
            next_cap.append((symbol, version))

    next_state = BistRefreshState(
        known_notification_ids=tuple(sorted(known_ids)),
        latest_kafif_ids=tuple(next_kafif),
        latest_kafif_submitted=tuple(next_kafif_sub),
        latest_thb_date=_iso(latest_thb),
        participation_keys=tuple(next_part),
        membership_keys=tuple(next_membership),
        capital_versions=tuple(next_cap),
    )
    si_writes = 0 if dry_run or not persist_si else published
    part_writes = 0 if dry_run or not persist_participation else part_published
    writes = si_writes + part_writes
    status = "completed" if not errors else "partial"
    return BistRefreshRun(
        run_id=run_id,
        job_name=JOB_NAME,
        started_at=started,
        finished_at=_now(),
        status=status,
        dry_run=dry_run,
        persist_si=persist_si,
        persist_participation=persist_participation,
        allow_live=allow_live,
        symbols_checked=len(requested),
        changes_detected=changes_n,
        symbols_processed=processed,
        snapshots_published=published,
        rows_skipped=skipped,
        writes=writes,
        errors=tuple(errors),
        participation_changes_detected=part_changes,
        participation_processed=part_processed,
        participation_published=part_published,
        participation_skipped=part_skipped,
        participation_errors=tuple(part_errors),
        latest_thb_date=_iso(latest_thb),
        missing_thb_dates=tuple(item.isoformat() for item in missing),
        securities=tuple(results),
        next_state=next_state,
    )


def _latest_kafif(rows: Sequence[KapKafifDiscovery]) -> Optional[KapKafifDiscovery]:
    from services.kap_kafif_parser import latest_kafif_discovery

    return latest_kafif_discovery(tuple(rows))


def _refresh_symbol(
    symbol: str,
    *,
    as_of: date,
    prior: BistRefreshState,
    cache: Any,
    latest_thb: Optional[date],
    missing: Sequence[date],
    discoveries: Sequence[KapFrDiscovery],
    documents: Sequence[KapPublicFinancialDocument],
    kafif_rows: Sequence[KapKafifDiscovery],
    participation: str,
    evidence: Any,
    capital: str,
    capital_version: str,
    events: Sequence[Any],
    dry_run: bool,
    persist_si: bool,
    persist_participation: bool,
    snapshot_repo: Any,
    participation_repo: Any,
    membership: Any,
    kafif_document: Any,
) -> BistSymbolRefresh:
    changes: list[str] = []
    known = prior.known_ids()
    new_annual = incremental_annual_targets(tuple(discoveries), known)
    kap_status = STATUS_NO_CHANGE
    latest_ids = tuple(
        row.notification_id for row in discoveries if getattr(row, "notification_id", "")
    )
    if new_annual:
        changes.append(CHANGE_FINANCIAL_FACTS)
        years_known = {
            row.year
            for row in discoveries
            if row.notification_id in known and row.year
        }
        if any(row.year and row.year not in years_known for row in new_annual):
            kap_status = STATUS_NEW_PERIOD
        else:
            kap_status = STATUS_CORRECTION
        if documents:
            history = build_kap_annual_history(symbol, documents)
            if history.restatements:
                kap_status = STATUS_RESTATEMENT

    kafif = _latest_kafif(kafif_rows)
    kafif_status = STATUS_NO_CHANGE
    kafif_id = kafif.disclosure_id if kafif is not None else prior.kafif_id(symbol)
    if kafif_is_newer(prior.kafif_id(symbol), prior.kafif_submitted(symbol), kafif):
        changes.append(CHANGE_PARTICIPATION)
        same_period = bool(
            kafif
            and prior.kafif_id(symbol)
            and kafif.financial_year
        )
        kafif_status = STATUS_CORRECTION if same_period else STATUS_NEW_PERIOD
    part_key = _json_key(evidence)
    if part_key and part_key != prior.participation_key(symbol) and CHANGE_PARTICIPATION not in changes:
        changes.append(CHANGE_PARTICIPATION)
        kafif_status = STATUS_CORRECTION
    mem_key = _membership_key(membership)
    if mem_key and mem_key != prior.membership_key(symbol) and CHANGE_PARTICIPATION not in changes:
        changes.append(CHANGE_PARTICIPATION)

    capital_status = STATUS_NO_CHANGE
    if capital_version and capital_version != prior.capital_version(symbol):
        changes.append(CHANGE_CAPITAL)
        capital_status = STATUS_NEW_PERIOD if prior.capital_version(symbol) else STATUS_CHECKED

    thb_status = STATUS_NO_CHANGE
    if missing:
        changes.append(CHANGE_PRICE_HISTORY)
        thb_status = STATUS_SOURCE_UNAVAILABLE

    series = load_cached_series(cache, symbol)
    if fixture_momentum_forbidden(series):
        return BistSymbolRefresh(
            symbol=symbol,
            kap_status=kap_status,
            kafif_status=kafif_status,
            capital_status=capital_status,
            thb_status=STATUS_BLOCKED,
            facts_status=STATUS_SKIPPED,
            reason=REASON_FIXTURE_MOMENTUM,
            latest_notification_ids=latest_ids,
            latest_kafif_id=kafif_id,
            latest_thb_date=_iso(latest_thb),
        )
    bulletin = load_cached_bulletin(cache, latest_thb) if latest_thb else None
    flags = events_from_thb_flags(series)
    new_days = set(missing)
    incremental_flags = tuple(
        item for item in flags if item.effective_date in new_days
    )
    merged = merge_official_events(events, flags)
    ca_status = STATUS_CHECKED
    if incremental_flags or events:
        changes.append(CHANGE_CORPORATE_ACTION)
    unresolved = False
    incoming = merge_official_events(events, incremental_flags)
    if incoming:
        start = min(item.effective_date for item in incoming)
        end = max(item.effective_date for item in incoming)
        if window_adjustment_status(incoming, start=start, end=end) == STATUS_UNRESOLVED:
            unresolved = True
            ca_status = STATUS_UNRESOLVED_CA

    previous_part = ""
    if participation_repo is not None:
        try:
            latest_part = participation_repo.get_latest(symbol)
        except Exception:
            latest_part = None
        if isinstance(latest_part, dict):
            previous_part = str(latest_part.get("status") or "")

    part_published = False
    part_skipped = False
    new_part = ""
    research_allowed = None
    part_error = ""
    if CHANGE_PARTICIPATION in changes:
        if official_participation_source_unavailable(membership, kafif_document):
            part_skipped = True
            part_error = "OFFICIAL_SOURCE_UNAVAILABLE_PRESERVE"
        else:
            saved = publish_official_bist_participation(
                symbol,
                membership=membership,
                kafif=kafif_document,
                repo=participation_repo,
                dry_run=dry_run,
                persist=persist_participation,
            )
            row = saved.row or {}
            new_part = str(row.get("status") or "")
            research_allowed = row.get("research_allowed")
            if saved.persistence_failed or saved.message.endswith("_PRESERVE"):
                part_skipped = True
                part_error = saved.message
            elif saved.saved:
                part_published = True
            elif saved.skipped_duplicate:
                part_skipped = True
            elif dry_run or not persist_participation or participation_repo is None:
                part_skipped = True
                if not new_part and saved.row:
                    new_part = str(saved.row.get("status") or "")

    if not changes:
        return BistSymbolRefresh(
            symbol=symbol,
            kap_status=kap_status,
            kafif_status=kafif_status,
            capital_status=capital_status,
            thb_status=thb_status,
            ca_status=ca_status,
            facts_status=STATUS_SKIPPED,
            si_status=STATUS_SKIPPED,
            latest_notification_ids=latest_ids,
            latest_kafif_id=kafif_id,
            latest_thb_date=_iso(latest_thb),
            reason=REASON_NO_CHANGE,
        )
    part_fields = dict(
        participation_published=part_published,
        participation_skipped=part_skipped,
        previous_participation_state=previous_part,
        new_participation_state=new_part,
        research_allowed=research_allowed,
        error=part_error,
    )
    if missing and set(changes) <= {CHANGE_PRICE_HISTORY, CHANGE_CORPORATE_ACTION}:
        return BistSymbolRefresh(
            symbol=symbol,
            changes=tuple(dict.fromkeys(changes)),
            kap_status=kap_status,
            kafif_status=kafif_status,
            capital_status=capital_status,
            thb_status=STATUS_SOURCE_UNAVAILABLE,
            ca_status=ca_status,
            facts_status=STATUS_SKIPPED,
            si_status=STATUS_SKIPPED,
            latest_notification_ids=latest_ids,
            latest_kafif_id=kafif_id,
            latest_thb_date=_iso(latest_thb),
            would_publish=False,
            reason=STATUS_SOURCE_UNAVAILABLE,
            **part_fields,
        )
    if unresolved:
        return BistSymbolRefresh(
            symbol=symbol,
            changes=tuple(dict.fromkeys(changes)),
            kap_status=kap_status,
            kafif_status=kafif_status,
            capital_status=capital_status,
            thb_status=thb_status,
            ca_status=STATUS_UNRESOLVED_CA,
            facts_status=STATUS_SKIPPED,
            si_status=STATUS_SKIPPED,
            latest_notification_ids=latest_ids,
            latest_kafif_id=kafif_id,
            latest_thb_date=_iso(latest_thb),
            would_publish=False,
            reason=REASON_UNRESOLVED_CA,
            **part_fields,
        )

    facts, _history, _events = compose_official_facts(
        symbol,
        documents=documents,
        bulletin=bulletin,
        series=series,
        capital_html=capital,
        official_events=merged,
    )
    effective_dry = dry_run or not persist_si or snapshot_repo is None
    si_status_ctx = new_part or participation
    si_research = True if research_allowed is None else bool(research_allowed)
    publish = publish_canonical_security_intelligence(
        facts,
        SecurityParticipationContext(status=si_status_ctx, research_allowed=si_research),
        snapshot_repo,
        dry_run=effective_dry,
    )
    would = bool(publish.view is not None and not publish.blocked and not publish.insufficient)
    if publish.blocked or publish.insufficient:
        reason = publish.block_reason or REASON_QUALITY_GATE
        si_status = STATUS_BLOCKED
        would = False
    elif dry_run or not persist_si:
        reason = REASON_DRY_RUN if dry_run else REASON_PERSIST_DISABLED
        si_status = STATUS_WOULD_PUBLISH
    else:
        reason = ""
        si_status = STATUS_CHECKED
    return BistSymbolRefresh(
        symbol=symbol,
        changes=tuple(dict.fromkeys(changes)),
        kap_status=kap_status,
        kafif_status=kafif_status,
        capital_status=capital_status,
        thb_status=thb_status,
        ca_status=ca_status,
        facts_status=STATUS_CHECKED,
        si_status=si_status,
        latest_notification_ids=latest_ids,
        latest_kafif_id=kafif_id,
        latest_thb_date=_iso(latest_thb),
        si_score=None if publish.view is None else publish.view.overall_score,
        si_state=None if publish.view is None else publish.view.investment_state,
        would_publish=would,
        published=bool(publish.published),
        reason=reason,
        **part_fields,
    )
