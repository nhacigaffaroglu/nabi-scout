from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from services.investment_thesis_contract import (
    InvestmentThesisView,
    ThesisChangeItem,
)


def _evidence_signature(view: InvestmentThesisView) -> Tuple[Tuple[str, str], ...]:
    signatures: List[Tuple[str, str]] = []
    for item in view.supporting_evidence + view.weakening_evidence:
        signatures.append((item.code, item.polarity))
    return tuple(sorted(signatures))


def _risk_signature(view: InvestmentThesisView) -> Tuple[str, ...]:
    return tuple(sorted(risk.code for risk in view.risks))


def _catalyst_signature(view: InvestmentThesisView) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((item.catalyst_id, item.status) for item in view.catalysts))


def detect_thesis_changes(
    current: InvestmentThesisView,
    previous: Mapping[str, Any] | InvestmentThesisView | None,
) -> Tuple[ThesisChangeItem, ...]:
    if previous is None:
        return ()

    if isinstance(previous, InvestmentThesisView):
        prev_view = previous
    else:
        payload = previous.get("thesis_payload") or previous.get("payload") or previous
        if not isinstance(payload, dict):
            return ()
        prev_view = _view_from_payload(payload)
        if prev_view is None:
            return ()

    changes: List[ThesisChangeItem] = []
    current_support = {item.code for item in current.supporting_evidence}
    prev_support = {item.code for item in prev_view.supporting_evidence}
    current_weak = {item.code for item in current.weakening_evidence}
    prev_weak = {item.code for item in prev_view.weakening_evidence}

    for code in sorted(current_support - prev_support):
        changes.append(
            ThesisChangeItem(
                code="NEW_SUPPORT",
                statement=f"Yeni destekleyici kanıt: {code}",
                evidence=(("code", code),),
            )
        )
    for code in sorted(current_weak - prev_weak):
        changes.append(
            ThesisChangeItem(
                code="NEW_WEAKNESS",
                statement=f"Yeni zayıflatan kanıt: {code}",
                evidence=(("code", code),),
            )
        )
    for code in sorted(prev_support - current_support):
        changes.append(
            ThesisChangeItem(
                code="SUPPORT_REMOVED",
                statement=f"Destekleyici kanıt kalktı: {code}",
                evidence=(("code", code),),
            )
        )
    for code in sorted(prev_weak - current_weak):
        changes.append(
            ThesisChangeItem(
                code="WEAKNESS_REMOVED",
                statement=f"Zayıflatan kanıt kalktı: {code}",
                evidence=(("code", code),),
            )
        )

    current_catalysts = {item.catalyst_id: item.status for item in current.catalysts}
    prev_catalysts = {item.catalyst_id: item.status for item in prev_view.catalysts}
    for catalyst_id in sorted(set(current_catalysts) - set(prev_catalysts)):
        changes.append(
            ThesisChangeItem(
                code="CATALYST_ADDED",
                statement=f"Yeni katalizör: {catalyst_id}",
                evidence=(("catalyst_id", catalyst_id),),
            )
        )
    for catalyst_id, status in prev_catalysts.items():
        if catalyst_id in current_catalysts and current_catalysts[catalyst_id] != status:
            if current_catalysts[catalyst_id] in {"RESOLVED", "PASSED"}:
                changes.append(
                    ThesisChangeItem(
                        code="CATALYST_RESOLVED",
                        statement=f"Katalizör tamamlandı: {catalyst_id}",
                        evidence=(("catalyst_id", catalyst_id), ("status", status)),
                    )
                )

    current_risks = _risk_signature(current)
    prev_risks = _risk_signature(prev_view)
    for code in sorted(set(current_risks) - set(prev_risks)):
        changes.append(
            ThesisChangeItem(
                code="RISK_ADDED",
                statement=f"Yeni risk: {code}",
                evidence=(("code", code),),
            )
        )
    for code in sorted(set(prev_risks) - set(current_risks)):
        changes.append(
            ThesisChangeItem(
                code="RISK_REMOVED",
                statement=f"Risk kalktı: {code}",
                evidence=(("code", code),),
            )
        )

    if current.valuation_context != prev_view.valuation_context:
        changes.append(
            ThesisChangeItem(
                code="VALUATION_CONTEXT_CHANGED",
                statement=(
                    f"Değerleme bağlamı {prev_view.valuation_context} → "
                    f"{current.valuation_context}"
                ),
                evidence=(
                    ("previous", prev_view.valuation_context),
                    ("current", current.valuation_context),
                ),
            )
        )
    if current.earnings_context != prev_view.earnings_context:
        changes.append(
            ThesisChangeItem(
                code="EARNINGS_CONTEXT_CHANGED",
                statement=(
                    f"Kazanç bağlamı {prev_view.earnings_context} → "
                    f"{current.earnings_context}"
                ),
                evidence=(
                    ("previous", prev_view.earnings_context),
                    ("current", current.earnings_context),
                ),
            )
        )
    if current.confidence != prev_view.confidence:
        changes.append(
            ThesisChangeItem(
                code="DATA_QUALITY_CHANGED",
                statement=(
                    f"Tez güveni {prev_view.confidence} → {current.confidence}"
                ),
                evidence=(
                    ("previous", prev_view.confidence),
                    ("current", current.confidence),
                ),
            )
        )
    return tuple(changes)


def _view_from_payload(payload: Mapping[str, Any]) -> InvestmentThesisView | None:
    try:
        from services.investment_thesis_service import thesis_view_from_dict

        return thesis_view_from_dict(dict(payload))
    except Exception:
        return None


def apply_change_summary(
    view: InvestmentThesisView,
    previous: Mapping[str, Any] | InvestmentThesisView | None,
) -> InvestmentThesisView:
    changes = detect_thesis_changes(view, previous)
    if changes == view.change_summary:
        return view
    return InvestmentThesisView(
        symbol=view.symbol,
        company_name=view.company_name,
        as_of=view.as_of,
        thesis_version=view.thesis_version,
        thesis_status=view.thesis_status,
        thesis_summary=view.thesis_summary,
        key_question=view.key_question,
        supporting_evidence=view.supporting_evidence,
        weakening_evidence=view.weakening_evidence,
        risks=view.risks,
        catalysts=view.catalysts,
        invalidation_conditions=view.invalidation_conditions,
        assumptions=view.assumptions,
        valuation_context=view.valuation_context,
        earnings_context=view.earnings_context,
        peer_context=view.peer_context,
        news_context=view.news_context,
        expectation_tensions=view.expectation_tensions,
        participation_context=view.participation_context,
        nabi_context=view.nabi_context,
        confidence=view.confidence,
        evidence_coverage=view.evidence_coverage,
        change_summary=changes,
        monitoring_plan=view.monitoring_plan,
        decision_intelligence=view.decision_intelligence,
        data_quality_notes=view.data_quality_notes,
        provenance=view.provenance,
    )
