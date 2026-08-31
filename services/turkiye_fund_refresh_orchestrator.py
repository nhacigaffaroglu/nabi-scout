"""Turkish fund snapshot refresh.

Default dry_run=true. Writes require --live plus persist flags and repos.
Credentials never enable writes. Does not persist 8E or call New Money.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from uuid import uuid4

from services.bist_refresh_contract import (
    REASON_DRY_RUN,
    REASON_LIVE_UNSAFE,
    REASON_NO_CHANGE,
    REASON_PILOT_SCOPE,
)
from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_participation import evaluate_turkiye_fund_participation
from services.turkiye_fund_persistence import (
    persist_fund_intelligence_snapshot,
    persist_participation_snapshot,
    schema_compatible,
)
from services.turkiye_fund_refresh_contract import (
    CHANGE_EIGHT_E,
    CHANGE_ECONOMIC_EXPOSURE,
    CHANGE_FUND_INTELLIGENCE,
    CHANGE_PARTICIPATION,
    CHANGE_PDR,
    CHANGE_TEFAS_PRICE,
    JOB_NAME,
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
    OUTCOME_ERROR,
    REASON_FORBIDDEN_LAYER,
    REASON_INVALID_PAYLOAD,
    REASON_PARTICIPATION_WRITE_FAILED,
    STATUS_BLOCKED,
    STATUS_NO_CHANGE,
    STATUS_PUBLISHED,
    STATUS_SOURCE_FAILURE,
    STATUS_WOULD_PUBLISH,
    TurkiyeFundLayerCounts,
    TurkiyeFundLayerResult,
    TurkiyeFundRefreshRun,
    TurkiyeFundRefreshState,
    TurkiyeFundSymbolRefresh,
)
from services.official_kap_pdr_evidence import load_captured_pdr_discovery
from services.turkiye_fund_source_dates import parse_official_date, source_as_of_bundle
from services.turkiye_fund_snapshot import (
    assert_ais_not_portfolio_cash,
    blocked_snapshot,
    economic_exposure_snapshot,
    eight_e_snapshot,
    fund_intelligence_snapshot,
    identity_snapshot,
    izahname_date_for,
    participation_snapshot,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _forbidden_persist(*, persist_economic_exposure: bool, persist_decisions: bool) -> bool:
    return bool(persist_economic_exposure or persist_decisions)


def _writes_enabled(
    *,
    cli_live: bool,
    persist_fund_intelligence: bool,
    persist_participation: bool,
    persist_economic_exposure: bool,
    persist_decisions: bool,
) -> bool:
    if _forbidden_persist(
        persist_economic_exposure=persist_economic_exposure,
        persist_decisions=persist_decisions,
    ):
        return False
    return bool(cli_live) and bool(persist_participation or persist_fund_intelligence)


def _safe_call(callback, default=None):
    try:
        return callback()
    except Exception:
        return default


def _pdr_published_at(fund_code: str) -> Optional[str]:
    discovery = _safe_call(lambda: load_captured_pdr_discovery(fund_code))
    if discovery is None:
        return None
    return parse_official_date(getattr(discovery, "publish_date", None))


def compute_source_as_of(
    provider: object,
    fund_code: str,
    *,
    calculated_at: Optional[str] = None,
) -> dict[str, Any]:
    series = _safe_call(lambda: provider.price_history(fund_code, period_months=12))
    pdr = _safe_call(lambda: provider.pdr_holdings(fund_code))
    kap = _safe_call(lambda: provider.kap_mandate(fund_code))
    return source_as_of_bundle(
        tefas_price=getattr(series, "last_date", None) if series is not None else None,
        kap_pdr=getattr(pdr, "report_period", None) if pdr is not None else None,
        kap_mandate=getattr(kap, "as_of", None) if kap is not None else None,
        kap_izahname=izahname_date_for(fund_code),
        kap_pdr_published_at=_pdr_published_at(fund_code),
        calculated_at=calculated_at,
    )


def compute_turkiye_fund_snapshots(
    fund_code: str,
    *,
    provider: Optional[object] = None,
    calculated_at: Optional[str] = None,
) -> dict[str, Any]:
    resolved = provider or default_tefas_fund_provider()
    sources = compute_source_as_of(resolved, fund_code, calculated_at=calculated_at)
    identity = _safe_call(lambda: resolved.turkiye_identity(fund_code))
    if identity is None:
        identity_row = blocked_snapshot(
            LAYER_IDENTITY,
            fund_code,
            source_as_of=sources,
            calculated_at=calculated_at,
            reason="IDENTITY_UNAVAILABLE",
        )
    else:
        identity_row = identity_snapshot(identity, source_as_of=sources, calculated_at=calculated_at)

    verdict = None
    if identity is not None:
        kap = _safe_call(lambda: resolved.kap_mandate(fund_code))
        if kap is not None:
            verdict = _safe_call(
                lambda: evaluate_turkiye_fund_participation(
                    fund_code,
                    identity_status=identity.identity_status,
                    official_name=identity.official_name,
                    umbrella_type=kap.umbrella_type,
                )
            )
    if verdict is None:
        participation_row = blocked_snapshot(
            LAYER_PARTICIPATION,
            fund_code,
            source_as_of=sources,
            calculated_at=calculated_at,
            reason="PARTICIPATION_EVIDENCE_UNAVAILABLE",
            target_table="participation_assessment_snapshots",
        )
    else:
        participation_row = participation_snapshot(
            verdict, source_as_of=sources, calculated_at=calculated_at
        )

    exposure = _safe_call(lambda: resolved.economic_classification(fund_code))
    if sources.get("kap_pdr") is None:
        exposure = None
    exposure_row = economic_exposure_snapshot(
        exposure,
        fund_code=fund_code,
        source_as_of=sources,
        calculated_at=calculated_at,
    )

    view = None
    if sources.get("tefas_price"):
        view = _safe_call(lambda: evaluate_official_fund_intelligence(fund_code, provider=resolved))
    if view is None:
        fi_row = blocked_snapshot(
            LAYER_FUND_INTELLIGENCE,
            fund_code,
            source_as_of=sources,
            calculated_at=calculated_at,
            reason="TEFAS_UNAVAILABLE",
            target_table="security_intelligence_snapshots",
        )
    else:
        facts = _safe_call(lambda: resolved.facts(fund_code))
        unit_price = getattr(facts, "nav", None) if facts is not None else None
        fi_row = fund_intelligence_snapshot(
            view,
            source_as_of=sources,
            calculated_at=calculated_at,
            exposure=exposure,
            research_allowed=bool(getattr(verdict, "research_allowed", False)),
            participation_status=getattr(verdict, "participation_status", None),
            unit_price=unit_price,
            unit_price_as_of=sources.get("tefas_price"),
            unit_price_currency="TRY",
        )

    decision = _safe_call(lambda: evaluate_official_fund_decision(fund_code, provider=resolved))
    if decision is None:
        eight_row = blocked_snapshot(
            LAYER_EIGHT_E,
            fund_code,
            source_as_of=sources,
            calculated_at=calculated_at,
            reason="EIGHT_E_UNAVAILABLE",
        )
    else:
        eight_row = eight_e_snapshot(
            decision,
            source_as_of=sources,
            calculated_at=calculated_at,
            upstream_ready=bool(
                identity_row.publishable
                and participation_row.publishable
                and fi_row.publishable
                and exposure_row.publishable
            ),
        )
    if fund_code == "AIS":
        assert_ais_not_portfolio_cash(exposure_row)
        assert_ais_not_portfolio_cash(fi_row)
    return {
        "source_as_of": sources,
        LAYER_IDENTITY: identity_row,
        LAYER_PARTICIPATION: participation_row,
        LAYER_FUND_INTELLIGENCE: fi_row,
        LAYER_ECONOMIC_EXPOSURE: exposure_row,
        LAYER_EIGHT_E: eight_row,
    }


def _layer_changes(
    fund_code: str,
    layer: str,
    snapshot,
    previous: TurkiyeFundRefreshState,
    sources: dict[str, Optional[str]],
) -> tuple[str, ...]:
    changes: list[str] = []
    prior_key = previous.layer_key(fund_code, layer)
    if prior_key and prior_key != snapshot.idempotency_key:
        if layer == LAYER_PARTICIPATION:
            changes.append(CHANGE_PARTICIPATION)
        elif layer == LAYER_FUND_INTELLIGENCE:
            changes.append(CHANGE_FUND_INTELLIGENCE)
        elif layer == LAYER_ECONOMIC_EXPOSURE:
            changes.append(CHANGE_ECONOMIC_EXPOSURE)
        elif layer == LAYER_EIGHT_E:
            changes.append(CHANGE_EIGHT_E)
        if previous.tefas_price_date(fund_code) and previous.tefas_price_date(fund_code) != (
            sources.get("tefas_price") or ""
        ):
            changes.append(CHANGE_TEFAS_PRICE)
        if previous.pdr_period(fund_code) and previous.pdr_period(fund_code) != (sources.get("kap_pdr") or ""):
            changes.append(CHANGE_PDR)
    return tuple(dict.fromkeys(changes))


def _compute_only_outcome(
    fund_code: str,
    layer: str,
    snapshot,
    previous: TurkiyeFundRefreshState,
    sources: dict[str, Optional[str]],
    *,
    blocked_reason: Optional[str] = None,
) -> TurkiyeFundLayerResult:
    if blocked_reason:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=snapshot.publishable,
            idempotency_key=snapshot.idempotency_key,
            reason=blocked_reason,
        )
    if not snapshot.publishable:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=False,
            idempotency_key=snapshot.idempotency_key,
            reason="LAYER_NOT_PUBLISHABLE",
        )
    prior = previous.layer_key(fund_code, layer)
    changes = _layer_changes(fund_code, layer, snapshot, previous, sources)
    if prior and prior == snapshot.idempotency_key:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_NO_CHANGE,
            publishable=True,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_NO_CHANGE,
        )
    return TurkiyeFundLayerResult(
        fund_code=fund_code,
        layer=layer,
        status=STATUS_WOULD_PUBLISH,
        would_publish=True,
        publishable=True,
        idempotency_key=snapshot.idempotency_key,
        reason=REASON_DRY_RUN,
        changes=changes,
    )


def _persist_outcome(
    fund_code: str,
    layer: str,
    snapshot,
    previous: TurkiyeFundRefreshState,
    sources: dict[str, Optional[str]],
    *,
    persist: bool,
    repo: Any,
    writer,
    blocked_reason: Optional[str] = None,
) -> TurkiyeFundLayerResult:
    if blocked_reason:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=snapshot.publishable,
            idempotency_key=snapshot.idempotency_key,
            reason=blocked_reason,
        )
    if not snapshot.publishable:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=False,
            idempotency_key=snapshot.idempotency_key,
            reason="LAYER_NOT_PUBLISHABLE",
        )
    if not schema_compatible(snapshot):
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=False,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_INVALID_PAYLOAD,
            error=REASON_INVALID_PAYLOAD,
        )
    prior = previous.layer_key(fund_code, layer)
    changes = _layer_changes(fund_code, layer, snapshot, previous, sources)
    if not persist or repo is None:
        if prior and prior == snapshot.idempotency_key:
            return TurkiyeFundLayerResult(
                fund_code=fund_code,
                layer=layer,
                status=STATUS_NO_CHANGE,
                publishable=True,
                idempotency_key=snapshot.idempotency_key,
                reason=REASON_NO_CHANGE,
            )
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_WOULD_PUBLISH,
            would_publish=True,
            publishable=True,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_DRY_RUN,
            changes=changes,
        )
    result = writer(repo, snapshot, dry_run=False)
    if result.invalid:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=False,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_INVALID_PAYLOAD,
            error=result.message,
        )
    if result.persistence_failed:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=OUTCOME_ERROR,
            publishable=True,
            idempotency_key=snapshot.idempotency_key,
            reason=result.message,
            error=result.message,
            changes=changes,
        )
    if result.skipped_duplicate:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_NO_CHANGE,
            publishable=True,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_NO_CHANGE,
        )
    if result.saved:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_PUBLISHED,
            published=True,
            publishable=True,
            idempotency_key=snapshot.idempotency_key,
            reason=STATUS_PUBLISHED,
            changes=changes,
        )
    return TurkiyeFundLayerResult(
        fund_code=fund_code,
        layer=layer,
        status=OUTCOME_ERROR,
        publishable=True,
        idempotency_key=snapshot.idempotency_key,
        reason=result.message or "PERSIST_FAILED",
        error=result.message,
    )


def _tally(counts: dict[str, int], outcome: TurkiyeFundLayerResult) -> None:
    counts["processed"] += 1
    if outcome.status == STATUS_PUBLISHED:
        counts["published"] += 1
    elif outcome.status == STATUS_WOULD_PUBLISH:
        counts["would_publish"] += 1
    elif outcome.status == STATUS_NO_CHANGE:
        counts["no_change"] += 1
    elif outcome.status == OUTCOME_ERROR:
        counts["errors"] += 1
    else:
        counts["blocked"] += 1


def _empty_run(
    *,
    started: str,
    funds: tuple[str, ...],
    status: str,
    reason: str,
    persist_fund_intelligence: bool,
    persist_participation: bool,
    persist_economic_exposure: bool,
    persist_decisions: bool,
    allow_live: bool,
    cli_live: bool,
) -> TurkiyeFundRefreshRun:
    return TurkiyeFundRefreshRun(
        run_id=str(uuid4()),
        job_name=JOB_NAME,
        started_at=started,
        finished_at=_stamp(),
        status=status,
        dry_run=True,
        persist_fund_intelligence=False,
        persist_participation=False,
        persist_economic_exposure=False,
        persist_decisions=False,
        allow_live=allow_live,
        cli_live=cli_live,
        symbols=funds,
        errors=(reason,),
        writes=0,
        funds=tuple(
            TurkiyeFundSymbolRefresh(
                fund_code=code,
                error=reason,
                layers=(
                    TurkiyeFundLayerResult(
                        fund_code=code,
                        layer=LAYER_IDENTITY,
                        status=STATUS_BLOCKED,
                        reason=reason,
                    ),
                ),
            )
            for code in funds
        ),
    )


def run_turkiye_fund_refresh(
    *,
    symbols: Optional[Sequence[str]] = None,
    dry_run: bool = True,
    persist_fund_intelligence: bool = False,
    persist_participation: bool = False,
    persist_economic_exposure: bool = False,
    persist_decisions: bool = False,
    allow_live: bool = False,
    allow_broad: bool = False,
    cli_live: bool = False,
    previous_state: Optional[TurkiyeFundRefreshState] = None,
    calculated_at: Optional[str] = None,
    provider: Optional[object] = None,
    participation_repo: Any = None,
    snapshot_repo: Any = None,
) -> TurkiyeFundRefreshRun:
    """Compute + change-detect. Persist only when cli_live + persist flags + repos."""
    del dry_run  # writes are gated by cli_live + persist flags, not this default
    started = _stamp()
    funds = tuple(str(item).strip().upper() for item in (symbols or PILOT_TEFAS_FUND_CODES) if item)
    previous = previous_state or TurkiyeFundRefreshState()
    forbidden = _forbidden_persist(
        persist_economic_exposure=persist_economic_exposure,
        persist_decisions=persist_decisions,
    )
    if forbidden:
        return _empty_run(
            started=started,
            funds=funds,
            status="LIVE_BLOCKED",
            reason=REASON_FORBIDDEN_LAYER,
            persist_fund_intelligence=persist_fund_intelligence,
            persist_participation=persist_participation,
            persist_economic_exposure=persist_economic_exposure,
            persist_decisions=persist_decisions,
            allow_live=allow_live,
            cli_live=cli_live,
        )
    writes_enabled = _writes_enabled(
        cli_live=cli_live,
        persist_fund_intelligence=persist_fund_intelligence,
        persist_participation=persist_participation,
        persist_economic_exposure=False,
        persist_decisions=False,
    )
    extra = [code for code in funds if code not in PILOT_TEFAS_FUND_CODES]
    if extra and writes_enabled and not allow_broad:
        return _empty_run(
            started=started,
            funds=funds,
            status="LIVE_BLOCKED",
            reason=REASON_PILOT_SCOPE,
            persist_fund_intelligence=persist_fund_intelligence,
            persist_participation=persist_participation,
            persist_economic_exposure=False,
            persist_decisions=False,
            allow_live=allow_live,
            cli_live=cli_live,
        )
    persist_part = writes_enabled and persist_participation
    persist_fi = writes_enabled and persist_fund_intelligence
    live_unsafe = (persist_part and participation_repo is None) or (
        persist_fi and snapshot_repo is None
    )
    persist_part = persist_part and participation_repo is not None and not live_unsafe
    persist_fi = persist_fi and snapshot_repo is not None and not live_unsafe
    effective_dry_run = not (persist_part or persist_fi)
    resolved = provider or default_tefas_fund_provider()
    rows: list[TurkiyeFundSymbolRefresh] = []
    errors: list[str] = []
    next_keys: list[tuple[str, str, str]] = []
    next_tefas: list[tuple[str, str]] = []
    next_pdr: list[tuple[str, str]] = []
    would = no_change = blocked = processed = published = 0
    change_count = 0
    part_counts = {
        "processed": 0,
        "published": 0,
        "would_publish": 0,
        "no_change": 0,
        "blocked": 0,
        "errors": 0,
    }
    fi_counts = dict(part_counts)
    persist_blocked_reason = REASON_LIVE_UNSAFE if live_unsafe else None
    for code in funds:
        try:
            bundle = compute_turkiye_fund_snapshots(code, provider=resolved, calculated_at=calculated_at)
            sources = bundle["source_as_of"]
            layer_rows = []
            fund_changes: list[str] = []
            participation_write_failed = False
            for layer in (
                LAYER_IDENTITY,
                LAYER_PARTICIPATION,
                LAYER_FUND_INTELLIGENCE,
                LAYER_ECONOMIC_EXPOSURE,
                LAYER_EIGHT_E,
            ):
                snapshot = bundle[layer]
                if layer == LAYER_PARTICIPATION:
                    outcome = _persist_outcome(
                        code,
                        layer,
                        snapshot,
                        previous,
                        sources,
                        persist=persist_part,
                        repo=participation_repo,
                        writer=persist_participation_snapshot,
                        blocked_reason=persist_blocked_reason if writes_enabled else None,
                    )
                    if persist_part and outcome.status in {OUTCOME_ERROR} or (
                        persist_part and outcome.reason == REASON_INVALID_PAYLOAD
                    ):
                        participation_write_failed = True
                    _tally(part_counts, outcome)
                elif layer == LAYER_FUND_INTELLIGENCE:
                    fi_block = persist_blocked_reason if writes_enabled else None
                    if persist_fi and participation_write_failed:
                        fi_block = REASON_PARTICIPATION_WRITE_FAILED
                    elif persist_fi and not bundle[LAYER_PARTICIPATION].publishable:
                        fi_block = REASON_PARTICIPATION_WRITE_FAILED
                    outcome = _persist_outcome(
                        code,
                        layer,
                        snapshot,
                        previous,
                        sources,
                        persist=persist_fi and not participation_write_failed,
                        repo=snapshot_repo,
                        writer=persist_fund_intelligence_snapshot,
                        blocked_reason=fi_block,
                    )
                    _tally(fi_counts, outcome)
                else:
                    outcome = _compute_only_outcome(
                        code, layer, snapshot, previous, sources
                    )
                layer_rows.append(outcome)
                fund_changes.extend(outcome.changes)
                processed += 1
                if outcome.status == STATUS_WOULD_PUBLISH:
                    would += 1
                elif outcome.status == STATUS_NO_CHANGE:
                    no_change += 1
                elif outcome.status == STATUS_PUBLISHED:
                    published += 1
                elif outcome.status == STATUS_BLOCKED:
                    blocked += 1
                elif outcome.status == OUTCOME_ERROR:
                    blocked += 1
                    errors.append(f"{code}:{layer}:{outcome.error or outcome.reason}")
                next_keys.append((code, layer, snapshot.idempotency_key))
            if sources.get("tefas_price"):
                next_tefas.append((code, str(sources["tefas_price"])))
            if sources.get("kap_pdr"):
                next_pdr.append((code, str(sources["kap_pdr"])))
            unique_changes = tuple(dict.fromkeys(fund_changes))
            change_count += len(unique_changes)
            rows.append(TurkiyeFundSymbolRefresh(fund_code=code, changes=unique_changes, layers=tuple(layer_rows)))
        except Exception as exc:
            errors.append(f"{code}:{exc}")
            blocked += 1
            rows.append(
                TurkiyeFundSymbolRefresh(
                    fund_code=code,
                    error=str(exc),
                    layers=(
                        TurkiyeFundLayerResult(
                            fund_code=code,
                            layer=LAYER_IDENTITY,
                            status=STATUS_SOURCE_FAILURE,
                            reason="UPSTREAM_FAILURE",
                            error=str(exc),
                        ),
                    ),
                )
            )
    writes = part_counts["published"] + fi_counts["published"]
    if errors:
        status = "ERROR"
    elif live_unsafe:
        status = "LIVE_BLOCKED"
    elif writes_enabled and not effective_dry_run:
        status = "LIVE"
    else:
        status = "DRY_RUN"
    return TurkiyeFundRefreshRun(
        run_id=str(uuid4()),
        job_name=JOB_NAME,
        started_at=started,
        finished_at=_stamp(),
        status=status,
        dry_run=effective_dry_run,
        persist_fund_intelligence=persist_fi,
        persist_participation=persist_part,
        persist_economic_exposure=False,
        persist_decisions=False,
        allow_live=allow_live,
        cli_live=cli_live,
        symbols=funds,
        changes_detected=change_count,
        processed=processed,
        published=published,
        would_publish=would,
        no_change=no_change,
        blocked=blocked,
        errors=tuple(errors),
        writes=writes,
        participation=TurkiyeFundLayerCounts(**part_counts),
        fund_intelligence=TurkiyeFundLayerCounts(**fi_counts),
        funds=tuple(rows),
        next_state=TurkiyeFundRefreshState(
            layer_keys=tuple(next_keys),
            tefas_price_dates=tuple(next_tefas),
            pdr_periods=tuple(next_pdr),
        ),
    )
