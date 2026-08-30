"""Dry-run Turkish fund snapshot refresh.

Default dry_run=true. Credentials never enable writes.
Does not call New Money, apply migrations, or persist snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from uuid import uuid4

from services.bist_refresh_contract import REASON_DRY_RUN, REASON_LIVE_UNSAFE, REASON_NO_CHANGE
from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_participation import evaluate_turkiye_fund_participation
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
    STATUS_BLOCKED,
    STATUS_NO_CHANGE,
    STATUS_SOURCE_FAILURE,
    STATUS_WOULD_PUBLISH,
    TurkiyeFundLayerResult,
    TurkiyeFundRefreshRun,
    TurkiyeFundRefreshState,
    TurkiyeFundSymbolRefresh,
)
from services.turkiye_fund_snapshot import (
    assert_ais_not_portfolio_cash,
    blocked_snapshot,
    economic_exposure_snapshot,
    eight_e_snapshot,
    fund_intelligence_snapshot,
    identity_snapshot,
    izahname_date_for,
    participation_snapshot,
    source_as_of_bundle,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _live_requested(
    *,
    dry_run: bool,
    persist_fund_intelligence: bool,
    persist_participation: bool,
    persist_economic_exposure: bool,
    persist_decisions: bool,
    allow_live: bool,
) -> bool:
    persist = any(
        (
            persist_fund_intelligence,
            persist_participation,
            persist_economic_exposure,
            persist_decisions,
        )
    )
    return (not dry_run) or persist or allow_live


def _safe_call(callback, default=None):
    try:
        return callback()
    except Exception:
        return default


def compute_source_as_of(provider: object, fund_code: str) -> dict[str, Optional[str]]:
    series = _safe_call(lambda: provider.price_history(fund_code, period_months=12))
    pdr = _safe_call(lambda: provider.pdr_holdings(fund_code))
    kap = _safe_call(lambda: provider.kap_mandate(fund_code))
    return source_as_of_bundle(
        tefas_price=getattr(series, "last_date", None) if series is not None else None,
        kap_pdr=getattr(pdr, "report_period", None) if pdr is not None else None,
        kap_mandate=getattr(kap, "as_of", None) if kap is not None else None,
        kap_izahname=izahname_date_for(fund_code),
    )


def compute_turkiye_fund_snapshots(
    fund_code: str,
    *,
    provider: Optional[object] = None,
    calculated_at: Optional[str] = None,
) -> dict[str, Any]:
    resolved = provider or default_tefas_fund_provider()
    sources = compute_source_as_of(resolved, fund_code)
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
        fi_row = fund_intelligence_snapshot(
            view,
            source_as_of=sources,
            calculated_at=calculated_at,
            exposure=exposure,
            research_allowed=bool(getattr(verdict, "research_allowed", False)),
            participation_status=getattr(verdict, "participation_status", None),
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


def _layer_outcome(
    fund_code: str,
    layer: str,
    snapshot,
    previous: TurkiyeFundRefreshState,
    sources: dict[str, Optional[str]],
    *,
    live_blocked: bool,
) -> TurkiyeFundLayerResult:
    if live_blocked:
        return TurkiyeFundLayerResult(
            fund_code=fund_code,
            layer=layer,
            status=STATUS_BLOCKED,
            publishable=snapshot.publishable,
            idempotency_key=snapshot.idempotency_key,
            reason=REASON_LIVE_UNSAFE,
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


def run_turkiye_fund_refresh(
    *,
    symbols: Optional[Sequence[str]] = None,
    dry_run: bool = True,
    persist_fund_intelligence: bool = False,
    persist_participation: bool = False,
    persist_economic_exposure: bool = False,
    persist_decisions: bool = False,
    allow_live: bool = False,
    previous_state: Optional[TurkiyeFundRefreshState] = None,
    calculated_at: Optional[str] = None,
    provider: Optional[object] = None,
) -> TurkiyeFundRefreshRun:
    """Compute + change-detect. Always writes=0 in this foundation sprint."""
    started = _stamp()
    funds = tuple(str(item).strip().upper() for item in (symbols or PILOT_TEFAS_FUND_CODES) if item)
    previous = previous_state or TurkiyeFundRefreshState()
    live_blocked = _live_requested(
        dry_run=dry_run,
        persist_fund_intelligence=persist_fund_intelligence,
        persist_participation=persist_participation,
        persist_economic_exposure=persist_economic_exposure,
        persist_decisions=persist_decisions,
        allow_live=allow_live,
    )
    resolved = provider or default_tefas_fund_provider()
    rows: list[TurkiyeFundSymbolRefresh] = []
    errors: list[str] = []
    next_keys: list[tuple[str, str, str]] = []
    next_tefas: list[tuple[str, str]] = []
    next_pdr: list[tuple[str, str]] = []
    would = no_change = blocked = processed = 0
    change_count = 0
    for code in funds:
        try:
            bundle = compute_turkiye_fund_snapshots(code, provider=resolved, calculated_at=calculated_at)
            sources = bundle["source_as_of"]
            layer_rows = []
            fund_changes: list[str] = []
            for layer in (
                LAYER_IDENTITY,
                LAYER_PARTICIPATION,
                LAYER_FUND_INTELLIGENCE,
                LAYER_ECONOMIC_EXPOSURE,
                LAYER_EIGHT_E,
            ):
                snapshot = bundle[layer]
                outcome = _layer_outcome(
                    code, layer, snapshot, previous, sources, live_blocked=live_blocked
                )
                layer_rows.append(outcome)
                fund_changes.extend(outcome.changes)
                processed += 1
                if outcome.status == STATUS_WOULD_PUBLISH:
                    would += 1
                elif outcome.status == STATUS_NO_CHANGE:
                    no_change += 1
                elif outcome.status == STATUS_BLOCKED:
                    blocked += 1
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
    status = "DRY_RUN"
    if errors:
        status = "ERROR"
    elif live_blocked:
        status = "LIVE_BLOCKED"
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
        allow_live=False,
        symbols=funds,
        changes_detected=change_count,
        processed=processed,
        would_publish=would,
        no_change=no_change,
        blocked=blocked,
        errors=tuple(errors),
        writes=0,
        funds=tuple(rows),
        next_state=TurkiyeFundRefreshState(
            layer_keys=tuple(next_keys),
            tefas_price_dates=tuple(next_tefas),
            pdr_periods=tuple(next_pdr),
        ),
    )
