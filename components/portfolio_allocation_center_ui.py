from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from components.nabi_design_system import render_section_title, render_status_badge
from services.portfolio_allocation_intelligence import (
    TARGET_SUM_EPSILON_PCT,
    AllocationCompleteness,
    AllocationDimension,
    AllocationIntelligenceView,
    AllocationPolicy,
    AllocationPolicyStatus,
    AllocationProvenance,
    AllocationTarget,
    DriftResult,
    DriftStatus,
    RoutingEvidenceQuality,
    RoutingStatus,
    build_allocation_intelligence,
    policy_is_configured,
)
from services.portfolio_allocation_policy_service import (
    AllocationPolicyStoreError,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_models import default_contribution_plan, default_wealth_goal_2031
from services.wealth_goal_planning import planning_conversion

HEADING = "Hedef Dağılım ve Sapma"
OBSERVABLE_HEADING = "Ölçülebilir Dağılım"
ROUTING_HEADING = "Yeni katkıyı nereye yönlendirmek dengeyi iyileştirir?"
PARTIAL_NOTE = (
    "Mevcut ağırlıklar yalnızca fiyatlanabilen varlıkların ölçülebilir bölümünü temsil eder."
)
SIMULATION_NOTE = (
    "Bu simülasyon bir al/sat önerisi değildir; yalnızca tanımladığınız hedef dağılıma "
    "göre yeni katkının etkisini gösterir."
)
UNCONFIGURED_ROUTING = "Hedef dağılım tanımlanmadan katkı yönlendirmesi hesaplanamaz."
FX_REQUIRED_COPY = "Kur varsayımı gerekli."
INDETERMINATE_ROUTING = "Kısmi değerleme nedeniyle katkı yönlendirmesi belirsiz."
SAVE_LABEL = "Hedef dağılımı kaydet"
RESET_LABEL = "Hedefi sıfırla"
PERSISTED_STATUS = "Kaydedilmiş hedef dağılım"
SETTINGS_UNAVAILABLE = "Hedef ayarları şu an kullanılamıyor."
SAVE_FAILED = "Hedef dağılım kaydedilemedi."
RESET_FAILED = "Hedef sıfırlanamadı."
PLANNED_CONTRIBUTION_LABEL = "Planlanan aylık katkı"
PLANNING_FX_SESSION_KEY = "wealth_os_2031_usdtry"
APPLIED_WEIGHTS_KEY = "portfolio_allocation_applied_weights"
DRAFT_WEIGHT_KEY_PREFIX = "portfolio_allocation_draft_"
CONTRIB_AMOUNT_KEY = "portfolio_allocation_contribution_amount"
CONTRIB_CURRENCY_KEY = "portfolio_allocation_contribution_currency"
HYDRATED_KEY = "portfolio_allocation_hydrated"
PERSISTED_FLAG_KEY = "portfolio_allocation_persisted"
LOAD_ERROR_KEY = "portfolio_allocation_load_error"
SAVE_ERROR_KEY = "portfolio_allocation_save_error"
RESET_ERROR_KEY = "portfolio_allocation_reset_error"

ASSET_CLASS_BUCKETS = ("equity", "etf", "sukuk", "cash", "other")
BUCKET_LABELS = {
    "equity": "Hisse",
    "etf": "ETF",
    "sukuk": "Sukuk / Sabit Getirili",
    "cash": "Nakit",
    "other": "Diğer",
}
STATUS_LABELS = {
    DriftStatus.OVERWEIGHT: "Hedef Üstü",
    DriftStatus.UNDERWEIGHT: "Hedef Altı",
    DriftStatus.ON_TARGET: "Hedefte",
    DriftStatus.INDETERMINATE: "Belirsiz",
}
STATUS_TONES = {
    DriftStatus.OVERWEIGHT: "warning",
    DriftStatus.UNDERWEIGHT: "warning",
    DriftStatus.ON_TARGET: "success",
    DriftStatus.INDETERMINATE: "info",
}
EVIDENCE_QUALITY_LABELS = {
    RoutingEvidenceQuality.COMPLETE: "tamam",
    RoutingEvidenceQuality.PARTIAL: "kısmi",
    RoutingEvidenceQuality.UNAVAILABLE: "yok",
}


@dataclass(frozen=True)
class PresentedDriftRow:
    bucket_id: str
    label: str
    observable_weight_pct: Optional[float]
    target_weight_pct: Optional[float]
    drift_pct: Optional[float]
    status_label: Optional[str]
    status_tone: str
    indeterminate: bool
    unpriced_symbols: Tuple[str, ...]
    limitation: Optional[str]


@dataclass(frozen=True)
class PresentedRouting:
    heading: str
    message: str
    status: str
    best_bucket_label: Optional[str]
    before_drift: Optional[float]
    after_drift: Optional[float]
    improvement: Optional[float]
    evidence_quality: Optional[str]
    limitation: Optional[str]


@dataclass(frozen=True)
class AllocationCenterPresentation:
    heading: str
    observable_heading: str
    routing_heading: str
    configured: bool
    persisted: bool
    settings_unavailable: bool
    remaining_pct: float
    draft_total: float
    can_save: bool
    apply_error: Optional[str]
    persistence_message: Optional[str]
    partial: bool
    partial_note: str
    simulation_note: str
    rows: Tuple[PresentedDriftRow, ...]
    routing: PresentedRouting
    chart_records: Tuple[Dict[str, Any], ...]


def draft_weight_key(bucket_id: str) -> str:
    return f"{DRAFT_WEIGHT_KEY_PREFIX}{bucket_id}"


def _as_float(value: Any) -> float:
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def draft_weights_from_session(session_state: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    source = session_state or {}
    return {
        bucket: max(_as_float(source.get(draft_weight_key(bucket), 0.0)), 0.0)
        for bucket in ASSET_CLASS_BUCKETS
    }


def remaining_target_pct(weights: Mapping[str, float]) -> float:
    return round(100.0 - sum(float(weights.get(bucket, 0.0)) for bucket in ASSET_CLASS_BUCKETS), 4)


def validate_target_weights(weights: Mapping[str, float]) -> Optional[str]:
    total = 0.0
    for bucket in ASSET_CLASS_BUCKETS:
        value = float(weights.get(bucket, 0.0))
        if value < 0:
            return "Hedef ağırlık negatif olamaz."
        if value > 100:
            return "Hedef ağırlık 100'ü aşamaz."
        total += value
    if abs(total - 100.0) > TARGET_SUM_EPSILON_PCT:
        return f"Toplam {total:.1f}% — hedef 100% olmalı, otomatik dengeleme yok."
    return None


def policy_from_weights(weights: Mapping[str, float]) -> Optional[AllocationPolicy]:
    normalized = {str(key).lower(): _as_float(value) for key, value in weights.items()}
    if validate_target_weights(normalized):
        return None
    targets = tuple(
        AllocationTarget(
            bucket_id=bucket,
            dimension=AllocationDimension.ASSET_CLASS,
            target_weight_pct=float(normalized.get(bucket, 0.0)),
            source=AllocationProvenance.USER_DEFINED,
        )
        for bucket in ASSET_CLASS_BUCKETS
    )
    policy = AllocationPolicy(targets=targets, provenance=AllocationProvenance.USER_DEFINED)
    policy.validate()
    return policy


def weights_from_policy(policy: AllocationPolicy) -> Dict[str, float]:
    by_id = {
        str(target.bucket_id).strip().lower(): float(target.target_weight_pct)
        for target in policy.targets
        if target.dimension == AllocationDimension.ASSET_CLASS
    }
    return {bucket: float(by_id.get(bucket, 0.0)) for bucket in ASSET_CLASS_BUCKETS}


def policy_from_session(session_state: Optional[Mapping[str, Any]]) -> Optional[AllocationPolicy]:
    source = session_state or {}
    applied = source.get(APPLIED_WEIGHTS_KEY)
    if not isinstance(applied, dict) or not applied:
        return None
    return policy_from_weights(applied)


def hydrate_allocation_session(
    session_state: Any,
    *,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> None:
    if session_state is None or session_state.get(HYDRATED_KEY):
        return
    session_state[HYDRATED_KEY] = True
    session_state.pop(LOAD_ERROR_KEY, None)
    if policy_service is None or not portfolio_id:
        session_state[PERSISTED_FLAG_KEY] = False
        return
    try:
        policy = policy_service.get_policy(portfolio_id)
    except AllocationPolicyStoreError as exc:
        session_state[LOAD_ERROR_KEY] = str(exc) or SETTINGS_UNAVAILABLE
        session_state[PERSISTED_FLAG_KEY] = False
        return
    except Exception:
        session_state[LOAD_ERROR_KEY] = SETTINGS_UNAVAILABLE
        session_state[PERSISTED_FLAG_KEY] = False
        return
    if policy is None:
        session_state[PERSISTED_FLAG_KEY] = False
        return
    dimensions = {target.dimension for target in policy.targets}
    if AllocationDimension.ECONOMIC_EXPOSURE in dimensions:
        from components.portfolio_economic_exposure_ui import hydrate_economic_exposure_from_policy

        hydrate_economic_exposure_from_policy(session_state, policy)
        session_state[PERSISTED_FLAG_KEY] = False
        return
    weights = weights_from_policy(policy)
    session_state[APPLIED_WEIGHTS_KEY] = dict(weights)
    for bucket, value in weights.items():
        session_state[draft_weight_key(bucket)] = float(value)
    session_state[PERSISTED_FLAG_KEY] = True


def save_allocation_policy_from_session(
    session_state: Any,
    *,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[str]:
    weights = draft_weights_from_session(session_state)
    error = validate_target_weights(weights)
    if error:
        return error
    policy = policy_from_weights(weights)
    if policy is None:
        return "Hedef dağılım henüz tanımlanmadı."
    if policy_service is not None and portfolio_id:
        try:
            stored = policy_service.save_policy(portfolio_id, policy)
        except AllocationPolicyStoreError as exc:
            return str(exc) or SAVE_FAILED
        except Exception:
            return SAVE_FAILED
        weights = weights_from_policy(stored)
        session_state[PERSISTED_FLAG_KEY] = True
    else:
        session_state[PERSISTED_FLAG_KEY] = False
    session_state[APPLIED_WEIGHTS_KEY] = dict(weights)
    for bucket, value in weights.items():
        session_state[draft_weight_key(bucket)] = float(value)
    session_state.pop(SAVE_ERROR_KEY, None)
    session_state.pop(RESET_ERROR_KEY, None)
    return None


def reset_allocation_policy_session(
    session_state: Any,
    *,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[str]:
    if policy_service is not None and portfolio_id:
        try:
            policy_service.delete_policy(portfolio_id)
        except AllocationPolicyStoreError as exc:
            return str(exc) or RESET_FAILED
        except Exception:
            return RESET_FAILED
    session_state.pop(APPLIED_WEIGHTS_KEY, None)
    for bucket in ASSET_CLASS_BUCKETS:
        session_state[draft_weight_key(bucket)] = 0.0
    session_state[PERSISTED_FLAG_KEY] = False
    session_state.pop(SAVE_ERROR_KEY, None)
    session_state.pop(RESET_ERROR_KEY, None)
    return None


def _session_conversion(session_state: Optional[Mapping[str, Any]], *, contribution_currency: str):
    if session_state is None:
        return None
    raw = session_state.get(PLANNING_FX_SESSION_KEY)
    if raw in (None, "", 0, 0.0):
        return None
    try:
        rate = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    goal = default_wealth_goal_2031()
    return planning_conversion(
        rate,
        contribution_currency=contribution_currency,
        goal_currency=goal.currency,
    )


def contribution_defaults(session_state: Optional[Mapping[str, Any]]) -> Tuple[Decimal, str]:
    plan = default_contribution_plan()
    source = session_state or {}
    amount = source.get(CONTRIB_AMOUNT_KEY, plan.starting_monthly)
    currency = str(source.get(CONTRIB_CURRENCY_KEY, plan.currency) or plan.currency)
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        value = plan.starting_monthly
    return value, currency.strip().upper() or plan.currency


def _format_weight(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{float(value):.1f}%"


def _present_rows(view: AllocationIntelligenceView) -> Tuple[PresentedDriftRow, ...]:
    buckets = {row.bucket_id: row for row in view.asset_class_buckets}
    drift = {row.bucket_id: row for row in view.drift}
    rows: list[PresentedDriftRow] = []
    order = list(ASSET_CLASS_BUCKETS)
    extra = [key for key in buckets if key not in order]
    for bucket_id in order + extra:
        bucket = buckets.get(bucket_id)
        drift_row: Optional[DriftResult] = drift.get(bucket_id)
        if bucket is None and drift_row is None:
            continue
        unpriced = bucket.unpriced_symbols if bucket else ()
        limitation = None
        if unpriced:
            limitation = (
                f"Kısmi değerleme — değerlenemeyen: {', '.join(unpriced)}. "
                "Bu kova %0 sayılmaz."
            )
        status = drift_row.status if drift_row else None
        rows.append(
            PresentedDriftRow(
                bucket_id=bucket_id,
                label=BUCKET_LABELS.get(bucket_id, bucket.label if bucket else bucket_id),
                observable_weight_pct=None if bucket is None else bucket.observable_weight_pct,
                target_weight_pct=None if drift_row is None else drift_row.target_weight_pct,
                drift_pct=None if drift_row is None else drift_row.drift_pct,
                status_label=STATUS_LABELS.get(status) if status else None,
                status_tone=STATUS_TONES.get(status, "neutral") if status else "neutral",
                indeterminate=status == DriftStatus.INDETERMINATE,
                unpriced_symbols=unpriced,
                limitation=limitation,
            )
        )
    return tuple(rows)


def _present_routing(view: AllocationIntelligenceView) -> PresentedRouting:
    route = view.routing[0] if view.routing else None
    if route is None or route.status == RoutingStatus.TARGET_NOT_CONFIGURED:
        return PresentedRouting(
            heading=ROUTING_HEADING,
            message=UNCONFIGURED_ROUTING,
            status=RoutingStatus.TARGET_NOT_CONFIGURED.value,
            best_bucket_label=None,
            before_drift=None,
            after_drift=None,
            improvement=None,
            evidence_quality=None,
            limitation=None,
        )
    if route.status == RoutingStatus.FX_REQUIRED:
        return PresentedRouting(
            heading=ROUTING_HEADING,
            message=FX_REQUIRED_COPY,
            status=route.status.value,
            best_bucket_label=None,
            before_drift=None,
            after_drift=None,
            improvement=None,
            evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
            limitation=FX_REQUIRED_COPY,
        )
    if route.status in {RoutingStatus.INDETERMINATE, RoutingStatus.UNAVAILABLE}:
        return PresentedRouting(
            heading=ROUTING_HEADING,
            message=(
                INDETERMINATE_ROUTING
                if route.status == RoutingStatus.INDETERMINATE
                else UNCONFIGURED_ROUTING
            ),
            status=route.status.value,
            best_bucket_label=None,
            before_drift=route.before_drift_score,
            after_drift=None,
            improvement=None,
            evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
            limitation=INDETERMINATE_ROUTING,
        )
    label = BUCKET_LABELS.get(route.best_bucket_id or "", route.best_bucket_id)
    return PresentedRouting(
        heading=ROUTING_HEADING,
        message=(
            f"Bu katkı varsayımıyla ölçülebilir sapmayı en fazla {label} "
            "bölgesine yönlendirme azaltıyor."
        ),
        status=route.status.value,
        best_bucket_label=label,
        before_drift=route.before_drift_score,
        after_drift=route.after_drift_score,
        improvement=route.improvement,
        evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
        limitation=PARTIAL_NOTE if route.evidence_quality == RoutingEvidenceQuality.PARTIAL else None,
    )


def _chart_records(rows: Sequence[PresentedDriftRow]) -> Tuple[Dict[str, Any], ...]:
    records: list[Dict[str, Any]] = []
    for row in rows:
        if row.target_weight_pct is None and row.observable_weight_pct is None:
            continue
        if row.observable_weight_pct is not None:
            records.append(
                {
                    "label": row.label,
                    "series": "Ölçülebilir",
                    "weight_pct": float(row.observable_weight_pct),
                    "indeterminate": row.indeterminate,
                }
            )
        if row.target_weight_pct is not None:
            records.append(
                {
                    "label": row.label,
                    "series": "Hedef",
                    "weight_pct": float(row.target_weight_pct),
                    "indeterminate": row.indeterminate,
                }
            )
    return tuple(records)


def present_allocation_center(
    view: AllocationIntelligenceView,
    *,
    draft_weights: Optional[Mapping[str, float]] = None,
    persisted: bool = False,
    settings_unavailable: bool = False,
    persistence_message: Optional[str] = None,
) -> AllocationCenterPresentation:
    draft = dict(draft_weights or {})
    total = sum(float(draft.get(bucket, 0.0)) for bucket in ASSET_CLASS_BUCKETS)
    remaining = remaining_target_pct(draft)
    has_draft = any(float(draft.get(bucket, 0.0)) for bucket in ASSET_CLASS_BUCKETS)
    apply_error = (
        validate_target_weights(draft) if has_draft else "Hedef dağılım henüz tanımlanmadı."
    )
    rows = _present_rows(view)
    return AllocationCenterPresentation(
        heading=HEADING,
        observable_heading=OBSERVABLE_HEADING,
        routing_heading=ROUTING_HEADING,
        configured=view.target_policy_status == AllocationPolicyStatus.CONFIGURED,
        persisted=bool(persisted),
        settings_unavailable=bool(settings_unavailable),
        remaining_pct=remaining,
        draft_total=round(total, 4),
        can_save=apply_error is None and not settings_unavailable,
        apply_error=None if apply_error is None else apply_error,
        persistence_message=persistence_message,
        partial=view.completeness != AllocationCompleteness.COMPLETE_ALLOCATION,
        partial_note=PARTIAL_NOTE,
        simulation_note=SIMULATION_NOTE,
        rows=rows,
        routing=_present_routing(view),
        chart_records=_chart_records(rows),
    )


def flatten_allocation_text(presented: AllocationCenterPresentation) -> str:
    parts = [
        presented.heading,
        presented.observable_heading,
        presented.routing_heading,
        presented.partial_note,
        presented.simulation_note,
        presented.routing.message,
        presented.apply_error or "",
        presented.persistence_message or "",
        PERSISTED_STATUS if presented.persisted else "",
        SETTINGS_UNAVAILABLE if presented.settings_unavailable else "",
    ]
    for row in presented.rows:
        parts.extend(
            [
                row.label,
                row.status_label or "",
                row.limitation or "",
                _format_weight(row.observable_weight_pct) or "",
                _format_weight(row.target_weight_pct) or "",
            ]
        )
    if presented.routing.best_bucket_label:
        parts.append(presented.routing.best_bucket_label)
    return "\n".join(part for part in parts if part)


def build_target_vs_observable_chart(records: Sequence[Mapping[str, Any]]):
    import altair as alt
    import pandas as pd

    from services.nabi_chart_theme import (
        CHART_HEIGHT_COMPACT,
        CHART_WIDTH,
        NABI_ACCENT,
        NABI_PRIMARY,
        _ensure_theme,
    )

    _ensure_theme()
    frame = pd.DataFrame(list(records))
    if frame.empty:
        return None
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                "label:N",
                sort=["Hisse", "ETF", "Sukuk / Sabit Getirili", "Nakit", "Diğer"],
                title=None,
            ),
            x=alt.X("weight_pct:Q", title="Ağırlık %", axis=alt.Axis(format=".1f")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(
                    domain=["Ölçülebilir", "Hedef"],
                    range=[NABI_ACCENT, NABI_PRIMARY],
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            yOffset="series:N",
            tooltip=[
                alt.Tooltip("label:N", title="Kova"),
                alt.Tooltip("series:N", title="Tür"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
            ],
        )
        .properties(
            width=CHART_WIDTH,
            height=max(CHART_HEIGHT_COMPACT, 28 * int(frame["label"].nunique())),
        )
    )


def build_allocation_for_ui(
    portfolio_view: PortfolioIntelligenceView,
    *,
    wealth=None,
    session_state: Optional[Any] = None,
    contribution_amount: Optional[Decimal] = None,
    contribution_currency: Optional[str] = None,
) -> AllocationIntelligenceView:
    policy = policy_from_session(session_state)
    amount, currency = contribution_defaults(session_state)
    if contribution_amount is not None:
        amount = contribution_amount
    if contribution_currency:
        currency = contribution_currency
    assets = wealth.list_assets() if wealth is not None else None
    positions = wealth.list_positions() if wealth is not None else None
    conversion = _session_conversion(session_state, contribution_currency=currency)
    configured = policy_is_configured(policy)
    return build_allocation_intelligence(
        portfolio_view,
        policy=policy,
        contribution_amount=amount if configured else None,
        contribution_currency=currency if configured else None,
        conversion=conversion,
        assets=assets,
        positions=positions,
    )


def _render_presented(
    presented: AllocationCenterPresentation,
    *,
    session_state,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> None:
    import streamlit as st

    render_section_title(presented.heading)
    st.caption(presented.partial_note if presented.partial else "Ölçülebilir dağılım tam kapsamlıdır.")
    if presented.settings_unavailable:
        st.info(presented.persistence_message or SETTINGS_UNAVAILABLE)
    elif presented.persisted:
        st.caption(PERSISTED_STATUS)
    cols = st.columns(len(ASSET_CLASS_BUCKETS))
    for col, bucket in zip(cols, ASSET_CLASS_BUCKETS):
        with col:
            st.number_input(
                BUCKET_LABELS[bucket],
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                key=draft_weight_key(bucket),
                help="Yüzde; toplam 100 olmalı.",
            )
    remaining = remaining_target_pct(draft_weights_from_session(session_state))
    if abs(remaining) <= TARGET_SUM_EPSILON_PCT:
        st.caption("Toplam 100%.")
    elif remaining > 0:
        st.caption(f"Kalan: {remaining:.1f}%")
    else:
        st.caption(f"Fazla tahsis: {abs(remaining):.1f}% — otomatik dengeleme yok.")
    actions = st.columns(2)
    with actions[0]:
        if st.button(SAVE_LABEL, disabled=not presented.can_save, key="portfolio_allocation_save"):
            error = save_allocation_policy_from_session(
                session_state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
            if error:
                session_state[SAVE_ERROR_KEY] = error
            else:
                st.rerun()
    with actions[1]:
        if st.button(RESET_LABEL, key="portfolio_allocation_reset"):
            error = reset_allocation_policy_session(
                session_state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
            if error:
                session_state[RESET_ERROR_KEY] = error
            else:
                st.rerun()
    save_error = session_state.get(SAVE_ERROR_KEY) or session_state.get(RESET_ERROR_KEY)
    if save_error:
        st.info(save_error)
    elif presented.apply_error and not presented.configured:
        st.info(presented.apply_error)
    render_section_title(presented.observable_heading)
    if presented.partial:
        st.caption("Kısmi değerleme · Ölçülebilir bölüm")
    for row in presented.rows:
        status = ""
        if row.status_label:
            if row.indeterminate:
                status = render_status_badge("Belirsiz", "info")
            else:
                status = render_status_badge(row.status_label, row.status_tone)
        observable = _format_weight(row.observable_weight_pct) or "ölçülemedi"
        target = _format_weight(row.target_weight_pct) or "—"
        drift = (
            _format_weight(row.drift_pct)
            if row.drift_pct is not None and not row.indeterminate
            else "—"
        )
        st.markdown(
            f"**{row.label}** · Ölçülebilir {observable} · Hedef {target} · Sapma {drift} {status}",
            unsafe_allow_html=True,
        )
        if row.limitation:
            st.caption(row.limitation)
    if presented.configured:
        chart = build_target_vs_observable_chart(presented.chart_records)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
            if any(row.indeterminate for row in presented.rows):
                st.caption("Belirsiz kovalar için kesin hedef üstü/altı sonucu gösterilmez.")
    render_section_title(presented.routing_heading)
    st.caption(presented.simulation_note)
    amount, currency = contribution_defaults(session_state)
    if CONTRIB_AMOUNT_KEY not in session_state:
        session_state[CONTRIB_AMOUNT_KEY] = float(amount)
    if CONTRIB_CURRENCY_KEY not in session_state:
        session_state[CONTRIB_CURRENCY_KEY] = currency
    inputs = st.columns(2)
    with inputs[0]:
        st.number_input(
            PLANNED_CONTRIBUTION_LABEL,
            min_value=0.0,
            step=100.0,
            key=CONTRIB_AMOUNT_KEY,
        )
    with inputs[1]:
        st.selectbox(
            "Katkı para birimi",
            options=["TRY", "USD"],
            key=CONTRIB_CURRENCY_KEY,
        )
    st.caption(presented.routing.message)
    if presented.routing.best_bucket_label and presented.routing.status == RoutingStatus.AVAILABLE.value:
        st.caption(
            f"Sapma skoru: {presented.routing.before_drift} → {presented.routing.after_drift} "
            f"(iyileşme {presented.routing.improvement})"
        )
        if presented.routing.evidence_quality:
            st.caption(f"Kanıt: {presented.routing.evidence_quality}")
        if presented.routing.limitation:
            st.caption(presented.routing.limitation)


def render_portfolio_allocation_center(
    *,
    portfolio_view: Optional[PortfolioIntelligenceView] = None,
    wealth=None,
    session_state: Optional[Any] = None,
    allocation: Optional[AllocationIntelligenceView] = None,
    empty_portfolio: bool = False,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[AllocationCenterPresentation]:
    """Target/drift UI. Policy writes occur only on explicit save or reset."""
    if empty_portfolio or (
        portfolio_view is not None and int(portfolio_view.total_position_count or 0) == 0
    ):
        return None
    try:
        import streamlit as st

        state = session_state if session_state is not None else st.session_state
        hydrate_allocation_session(
            state,
            policy_service=policy_service,
            portfolio_id=portfolio_id,
        )
        from components.portfolio_economic_exposure_ui import (
            DIMENSION_LABELS,
            DIMENSION_VIEW_KEY,
            VIEW_ASSET_CLASS,
            VIEW_ECONOMIC_EXPOSURE,
            render_economic_exposure_center,
        )

        if DIMENSION_VIEW_KEY not in state:
            state[DIMENSION_VIEW_KEY] = VIEW_ASSET_CLASS
        selected = st.radio(
            "Dağılım görünümü",
            options=[VIEW_ASSET_CLASS, VIEW_ECONOMIC_EXPOSURE],
            format_func=lambda value: DIMENSION_LABELS[value],
            key=DIMENSION_VIEW_KEY,
            horizontal=True,
        )
        if selected == VIEW_ECONOMIC_EXPOSURE:
            if portfolio_view is None:
                return None
            return render_economic_exposure_center(
                portfolio_view=portfolio_view,
                wealth=wealth,
                session_state=state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
        view = allocation
        if view is None:
            if portfolio_view is None:
                return None
            view = build_allocation_for_ui(
                portfolio_view,
                wealth=wealth,
                session_state=state,
            )
        unavailable = bool(state.get(LOAD_ERROR_KEY))
        persisted = bool(state.get(PERSISTED_FLAG_KEY)) and not unavailable
        persistence_message = (
            state.get(LOAD_ERROR_KEY)
            or state.get(SAVE_ERROR_KEY)
            or state.get(RESET_ERROR_KEY)
        )
        presented = present_allocation_center(
            view,
            draft_weights=draft_weights_from_session(state),
            persisted=persisted,
            settings_unavailable=unavailable,
            persistence_message=persistence_message,
        )
        _render_presented(
            presented,
            session_state=state,
            policy_service=policy_service,
            portfolio_id=portfolio_id,
        )
        return presented
    except Exception:
        return None
