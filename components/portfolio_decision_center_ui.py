from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from components.nabi_design_system import (
    render_section_title,
    render_status_badge,
)
from services.portfolio_allocation_intelligence import build_allocation_intelligence
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
    build_portfolio_decision,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_models import (
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import planning_conversion

HEADING = "Şimdi neye odaklanmalıyım?"
DISCLAIMER = (
    "Bu alan veri ve planlama önceliklerini gösterir; otomatik al/sat önerisi üretmez."
)
HEALTHY_MESSAGE = "Şu anda öne çıkan bir veri veya planlama açığı görünmüyor."
UNAVAILABLE_MESSAGE = "Eylem merkezi şu anda kullanılamıyor."
EVIDENCE_EXPANDER_LABEL = "Bu öneriler neye dayanıyor?"
MAX_VISIBLE_ACTIONS = 5
PLANNING_FX_SESSION_KEY = "wealth_os_2031_usdtry"

CATEGORY_LABELS = {
    DecisionCategory.DATA: "Veri",
    DecisionCategory.PLAN: "Plan",
    DecisionCategory.PORTFOLIO: "Portföy",
    DecisionCategory.MONITOR: "İzleme",
}
PRIORITY_LABELS = {
    DecisionPriority.CRITICAL: "Kritik",
    DecisionPriority.HIGH: "Yüksek",
    DecisionPriority.MEDIUM: "Orta",
    DecisionPriority.LOW: "Düşük",
    DecisionPriority.INFO: "Bilgi",
}
PRIORITY_TONES = {
    DecisionPriority.CRITICAL: "danger",
    DecisionPriority.HIGH: "warning",
    DecisionPriority.MEDIUM: "warning",
    DecisionPriority.LOW: "info",
    DecisionPriority.INFO: "info",
}
LIMITATION_COPY = {
    "PARTIAL_VALUATION": (
        "Kısmi değerleme: ölçülebilen tutar alt sınırdır; eksik varlıklar sıfır sayılmaz."
    ),
    "LOWER_BOUND_MARKET_VALUE": "Portföy değeri alt sınır olarak gösterilir.",
    "FX_CONVERSION_REQUIRED": (
        "TRY→USD projeksiyonu için açık bir planlama kur varsayımı gerekli. "
        "Bu varsayım tahmin değildir."
    ),
    "PERFORMANCE_EVIDENCE_INCOMPLETE": (
        "Performans kanıtı yetersiz; dönem getirisi iddia edilmez."
    ),
    "WEIGHTS_USE_PRICED_MV_ONLY": (
        "Yoğunlaşma oranı fiyatlı / gözlemlenebilir kısma göredir."
    ),
    "CONTRIBUTION_EVIDENCE_INCOMPLETE": (
        "Katkı kanıtı eksik; alış işlemleri nakit yatırma sayılmaz."
    ),
    "TARGET_NOT_CONFIGURED": "Kayıtlı hedef dağılım yok.",
    "OBSERVABLE_ALLOCATION_ONLY": (
        "Sapma yalnızca ölçülebilir bölüme göredir; eksik fiyatlı varlıklar sıfır sayılmaz."
    ),
    "EXPOSURE_CLASSIFICATION_INCOMPLETE": (
        "Ekonomik maruziyet sınıflandırması eksik olduğu için bazı sapma sonuçları belirsiz olabilir."
    ),
}
FX_DIRECTION = "Wealth → 2031 Hedef sekmesindeki planlama kuru alanını kullanın."
CONTRIBUTION_DIRECTION = (
    "Katkı takibi için yatırma/çekme geçmişi gerekir; alış kayıtları yeterli değildir."
)
PLAN_DIRECTION = "Wealth → 2031 Hedef sekmesinden katkı planını gözden geçirin."
ALLOCATION_DIRECTION = (
    "Hedef Dağılım ve Sapma bölümünden hedefi kaydedin veya sapmayı gözden geçirin."
)
EVIDENCE_QUALITY_LABELS = {
    "COMPLETE": "tamam",
    "PARTIAL": "kısmi",
    "UNAVAILABLE": "yok",
}
_SUMMARY_COVERED_LIMITATIONS = {
    "PARTIAL_VALUATION",
    "LOWER_BOUND_MARKET_VALUE",
    "FX_CONVERSION_REQUIRED",
    "CONTRIBUTION_EVIDENCE_INCOMPLETE",
    "PERFORMANCE_EVIDENCE_INCOMPLETE",
}


@dataclass(frozen=True)
class PresentedAction:
    id: str
    category_label: str
    priority_label: str
    priority_tone: str
    title: str
    explanation: str
    evidence_lines: Tuple[str, ...]
    limitation: Optional[str]
    direction: Optional[str]


@dataclass(frozen=True)
class ActionCenterPresentation:
    heading: str
    healthy: bool
    healthy_message: Optional[str]
    disclaimer: str
    visible_actions: Tuple[PresentedAction, ...]
    hidden_count: int
    evidence_summary: Tuple[str, ...]
    action_ids: Tuple[str, ...]


def _join_tr(items: Sequence[str]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} ve {values[1]}"
    return f"{', '.join(values[:-1])} ve {values[-1]}"


def _money(value: Any, currency: str = "USD") -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        amount = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if str(currency).upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _unvalued_symbols(action: DecisionAction) -> Tuple[str, ...]:
    raw = action.context.get("unvalued_symbols")
    if isinstance(raw, (list, tuple)):
        symbols = tuple(str(item).strip() for item in raw if str(item).strip())
        if symbols:
            return symbols
    skip = {"PARTIAL_VALUATION", "LOWER_BOUND_MARKET_VALUE"}
    return tuple(item for item in action.evidence if item not in skip)


def _limitation_copy(action: DecisionAction) -> Optional[str]:
    for code in action.limitations:
        text = LIMITATION_COPY.get(code)
        if text:
            return text
    return None


def _present_action(action: DecisionAction) -> PresentedAction:
    category = CATEGORY_LABELS[action.category]
    priority = PRIORITY_LABELS[action.priority]
    tone = PRIORITY_TONES.get(action.priority, "info")
    limitation = _limitation_copy(action)
    if action.id == "incomplete_valuation":
        symbols = _unvalued_symbols(action)
        listed = _join_tr(symbols) or "bazı varlıklar"
        evidence = []
        if symbols:
            evidence.append(f"Değerlenemeyen semboller: {', '.join(symbols)}")
        lower = _money(action.context.get("current_value_lower_bound"))
        if lower:
            evidence.append(f"Ölçülebilen portföy değeri: en az {lower}")
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Portföy değerlemesini tamamla",
            explanation=(
                f"{listed} henüz değerlenemediği için toplam portföy değeri "
                "alt sınır olarak gösteriliyor."
            ),
            evidence_lines=tuple(evidence),
            limitation=limitation,
            direction="Eksik fiyatlı semboller listelenir; fiyat sağlayıcısı çağrılmaz.",
        )
    if action.id == "missing_planning_fx":
        pair = action.evidence[0] if action.evidence else "TRY->USD"
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="2031 planı için kur varsayımı gerekli",
            explanation=(
                "Gelecek TRY katkıları, açık bir planlama kur varsayımı olmadan "
                "USD hedefe çevrilemez. Kullanıcı varsayımı bir tahmin değildir."
            ),
            evidence_lines=(f"Eksik planlama dönüşümü: {pair}",),
            limitation=limitation,
            direction=FX_DIRECTION,
        )
    if action.id == "contribution_evidence_incomplete":
        quality = str(
            action.context.get("evidence_quality")
            or (action.evidence[0] if action.evidence else "")
        ).strip().upper()
        quality_label = EVIDENCE_QUALITY_LABELS.get(quality, "eksik")
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Katkı geçmişini tamamla",
            explanation=(
                "Alış (BUY) işlemleri nakit yatırma kanıtı değildir; gerçek katkı "
                "takibi henüz tamamlanmadı."
            ),
            evidence_lines=(f"Katkı kanıtı: {quality_label}",),
            limitation=limitation,
            direction=CONTRIBUTION_DIRECTION,
        )
    if action.id == "contribution_plan_below_required":
        planned = action.context.get("planned_monthly")
        required = action.context.get("required_starting_monthly")
        evidence = []
        if planned is not None:
            evidence.append(f"Planlanan aylık: {planned}")
        if required is not None:
            evidence.append(f"Gerekli başlangıç aylık: {required}")
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Katkı planını gözden geçir",
            explanation=(
                "Mevcut plan, hedefe ulaşmak için gereken başlangıç aylık katkının "
                "altında görünüyor. Bu bir menkul kıymet al/sat önerisi değildir."
            ),
            evidence_lines=tuple(evidence),
            limitation=limitation,
            direction=PLAN_DIRECTION,
        )
    if action.id == "concentration_review":
        symbol = str(action.context.get("symbol") or (action.evidence[0] if action.evidence else ""))
        weight = action.context.get("weight_pct")
        threshold = action.context.get("threshold_pct")
        partial = bool(action.context.get("partial_valuation"))
        weight_txt = f"{float(weight):.1f}%" if weight is not None else ""
        scope = (
            "fiyatlı / gözlemlenebilir kısma göre "
            if partial
            else ""
        )
        explanation = (
            f"{symbol} {scope}yaklaşık {weight_txt} paya sahip ve mevcut "
            f"%{float(threshold):.0f} inceleme eşiğine ulaştı. Bu bir satış önerisi değildir."
            if symbol and weight_txt and threshold is not None
            else "Yoğunlaşma, fiyatlı kısma göre inceleme eşiğine ulaştı. Bu bir satış önerisi değildir."
        )
        evidence = []
        if symbol:
            evidence.append(f"Sembol: {symbol}")
        if weight_txt:
            evidence.append(f"Gözlemlenen pay: {weight_txt}")
        if partial:
            evidence.append("Kapsam: yalnızca fiyatlı / gözlemlenebilir kısım")
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Yoğunlaşmayı gözden geçir",
            explanation=explanation,
            evidence_lines=tuple(evidence),
            limitation=limitation,
            direction=None,
        )
    if action.id == "allocation_target_not_configured":
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Hedef portföy dağılımını tanımla",
            explanation=(
                "Kayıtlı bir hedef dağılım yok. Sapma ve katkı yönlendirmesi "
                "hedef tanımlanmadan hesaplanmaz."
            ),
            evidence_lines=(),
            limitation=limitation,
            direction=ALLOCATION_DIRECTION,
        )
    if action.id == "economic_exposure_incomplete":
        raw = action.context.get("unknown_exposure_symbols")
        symbols = tuple(str(item) for item in raw) if isinstance(raw, (list, tuple)) else ()
        evidence = []
        if symbols:
            evidence.append("Sınıflandırılamayan: " + ", ".join(symbols))
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Ekonomik maruziyet sınıflandırmasını tamamla",
            explanation=(
                "Bazı araçların ekonomik maruziyeti sınıflandırılamadı. "
                "Bu, isim veya ticker’dan bir kova iddia etmez."
            ),
            evidence_lines=tuple(evidence),
            limitation=limitation,
            direction=ALLOCATION_DIRECTION,
        )
    if action.id == "allocation_drift_review":
        evidence = [
            line
            for line in action.evidence
            if line not in {"MATERIAL_OBSERVABLE_DRIFT", "OBSERVABLE_ALLOCATION_ONLY"}
        ]
        if action.context.get("allocation_evidence_incomplete"):
            evidence.append("Kanıt: ölçülebilir bölüm; kısmi değerleme")
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="Hedef dağılımdan sapmayı gözden geçir",
            explanation=action.explanation,
            evidence_lines=tuple(evidence),
            limitation=limitation,
            direction=ALLOCATION_DIRECTION,
        )
    if action.id == "continue_observation":
        return PresentedAction(
            id=action.id,
            category_label=category,
            priority_label=priority,
            priority_tone=tone,
            title="İzlemeye devam et",
            explanation=(
                "Mevcut kanıt yüksek veya orta öncelikli bir müdahaleyi desteklemiyor. "
                "Planı ve portföyü izlemeye devam edin."
            ),
            evidence_lines=(),
            limitation=limitation,
            direction=None,
        )
    return PresentedAction(
        id=action.id,
        category_label=category,
        priority_label=priority,
        priority_tone=tone,
        title=action.title,
        explanation=action.explanation,
        evidence_lines=tuple(action.evidence),
        limitation=limitation,
        direction=None,
    )


def _evidence_summary(decision: PortfolioDecisionView) -> Tuple[str, ...]:
    by_id = {row.id: row for row in decision.actions}
    lines: list[str] = []
    valuation = by_id.get("incomplete_valuation")
    if valuation:
        symbols = _unvalued_symbols(valuation)
        listed = ", ".join(symbols) if symbols else "eksik varlıklar"
        lines.append(f"Değerleme: kısmi — {listed}")
        lower = _money(valuation.context.get("current_value_lower_bound"))
        if lower:
            lines.append(f"Ölçülebilen portföy değeri: en az {lower}")
    else:
        lines.append("Değerleme: ölçülebilen kapsam tamam")
    if "missing_planning_fx" in by_id:
        lines.append(
            "2031 projeksiyonu: açık planlama kur varsayımı yok "
            "(varsayım tahmin değildir)."
        )
    else:
        lines.append("2031 projeksiyonu: kur varsayımı tarafı tamam veya gerekmiyor.")
    contrib = by_id.get("contribution_evidence_incomplete")
    if contrib:
        lines.append(
            "Katkı kanıtı: eksik — alış işlemleri nakit yatırma sayılmaz."
        )
    else:
        lines.append("Katkı kanıtı: tamam")
    if "PERFORMANCE_EVIDENCE_INCOMPLETE" in decision.limitations:
        lines.append("Performans kanıtı: yetersiz — getiri iddiası yok.")
    else:
        lines.append("Performans kanıtı: kullanılabilir")
    for code in decision.limitations:
        if code in _SUMMARY_COVERED_LIMITATIONS:
            continue
        text = LIMITATION_COPY.get(code)
        if text and text not in lines:
            lines.append(text)
    return tuple(lines)


def present_action_center(decision: PortfolioDecisionView) -> ActionCenterPresentation:
    ordered = tuple(decision.actions)
    visible_source = ordered[:MAX_VISIBLE_ACTIONS]
    hidden = max(len(ordered) - MAX_VISIBLE_ACTIONS, 0)
    healthy = (
        decision.primary_action.id == "continue_observation"
        and decision.primary_action.category == DecisionCategory.MONITOR
    )
    return ActionCenterPresentation(
        heading=HEADING,
        healthy=healthy,
        healthy_message=HEALTHY_MESSAGE if healthy else None,
        disclaimer=DISCLAIMER,
        visible_actions=tuple(_present_action(row) for row in visible_source),
        hidden_count=hidden,
        evidence_summary=_evidence_summary(decision),
        action_ids=tuple(row.id for row in ordered),
    )


def flatten_presentation_text(presented: ActionCenterPresentation) -> str:
    parts = [presented.heading, presented.disclaimer]
    if presented.healthy_message:
        parts.append(presented.healthy_message)
    for action in presented.visible_actions:
        parts.extend(
            [
                action.category_label,
                action.priority_label,
                action.title,
                action.explanation,
                action.limitation or "",
                action.direction or "",
                *action.evidence_lines,
            ]
        )
    parts.extend(presented.evidence_summary)
    if presented.hidden_count:
        parts.append(f"+ {presented.hidden_count} ek odak maddesi")
    return "\n".join(part for part in parts if part)


def _session_conversion(session_state: Optional[Any]):
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
    plan = default_contribution_plan()
    return planning_conversion(
        rate,
        contribution_currency=plan.currency,
        goal_currency=goal.currency,
    )


def build_decision_for_ui(
    portfolio_view: PortfolioIntelligenceView,
    *,
    wealth=None,
    accounts: Sequence[Dict[str, Any]] = (),
    session_state: Optional[Any] = None,
    as_of=None,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> PortfolioDecisionView:
    """Read-only wrapper around the Prompt 1 engine. No providers, no writes."""
    transactions: Iterable[Dict[str, Any]] = ()
    account_ids: Sequence[str] = ()
    positions = None
    assets = None
    if wealth is not None:
        assets = wealth.list_assets()
        positions = wealth.list_positions()
        transactions = wealth.list_transactions(limit=2000)
        account_ids = [str(row.get("id") or "") for row in accounts]
    allocation_signals = None
    if policy_service is not None and portfolio_id:
        try:
            policy = policy_service.get_policy(portfolio_id)
            plan = default_contribution_plan()
            exposure_buckets = None
            if policy is not None and any(
                target.dimension.value == "ECONOMIC_EXPOSURE" for target in policy.targets
            ):
                from components.portfolio_economic_exposure_ui import (
                    allocation_buckets_from_exposure,
                    build_economic_exposure_for_ui,
                )

                exposure = build_economic_exposure_for_ui(
                    portfolio_view,
                    wealth=wealth,
                    session_state=session_state,
                )
                exposure_buckets = allocation_buckets_from_exposure(exposure)
            allocation = build_allocation_intelligence(
                portfolio_view,
                policy=policy,
                contribution_amount=plan.starting_monthly,
                contribution_currency=plan.currency,
                conversion=_session_conversion(session_state),
                assets=assets,
                positions=positions,
                exposure_buckets=exposure_buckets,
            )
            allocation_signals = allocation.signals
        except Exception:
            allocation_signals = None
    return build_portfolio_decision(
        portfolio_view,
        as_of_date=as_of,
        conversion=_session_conversion(session_state),
        transactions=transactions,
        account_ids=account_ids,
        positions=positions,
        assets=assets,
        allocation_signals=allocation_signals,
    )


def _render_unavailable() -> None:
    import streamlit as st

    render_section_title(HEADING)
    st.info(UNAVAILABLE_MESSAGE)


def _render_presented(presented: ActionCenterPresentation) -> None:
    import streamlit as st

    render_section_title(presented.heading)
    st.caption(presented.disclaimer)
    if presented.healthy and presented.healthy_message:
        st.success(presented.healthy_message)
    if not presented.visible_actions:
        return
    primary = presented.visible_actions[0]
    remaining = presented.visible_actions[1:]
    with st.container(border=True):
        badges = " ".join(
            [
                render_status_badge(primary.priority_label, primary.priority_tone),
                render_status_badge(primary.category_label, "info"),
            ]
        )
        st.markdown(f"{badges}", unsafe_allow_html=True)
        st.markdown(f"**{primary.title}**")
        st.write(primary.explanation)
        for line in primary.evidence_lines:
            st.caption(line)
        if primary.limitation:
            st.caption(primary.limitation)
        if primary.direction:
            st.caption(primary.direction)
    for row in remaining:
        st.markdown(
            f"**{row.priority_label} · {row.category_label}** — {row.title}"
        )
        st.caption(row.explanation)
        for line in row.evidence_lines:
            st.caption(line)
        if row.limitation:
            st.caption(row.limitation)
        if row.direction:
            st.caption(row.direction)
    if presented.hidden_count:
        st.caption(f"+ {presented.hidden_count} ek odak maddesi")
    with st.expander(EVIDENCE_EXPANDER_LABEL):
        st.caption(presented.disclaimer)
        for line in presented.evidence_summary:
            st.caption(f"• {line}")


def render_portfolio_decision_center(
    *,
    portfolio_view: Optional[PortfolioIntelligenceView] = None,
    wealth=None,
    accounts: Sequence[Dict[str, Any]] = (),
    decision: Optional[PortfolioDecisionView] = None,
    session_state: Optional[Any] = None,
    empty_portfolio: bool = False,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[ActionCenterPresentation]:
    """Render engine outputs only. Never invent actions or trigger providers."""
    if empty_portfolio or (
        portfolio_view is not None and int(portfolio_view.total_position_count or 0) == 0
    ):
        return None
    try:
        view = decision
        if view is None:
            if portfolio_view is None:
                _render_unavailable()
                return None
            import streamlit as st

            view = build_decision_for_ui(
                portfolio_view,
                wealth=wealth,
                accounts=accounts,
                session_state=session_state if session_state is not None else st.session_state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
        presented = present_action_center(view)
        _render_presented(presented)
        return presented
    except Exception:
        _render_unavailable()
        return None
