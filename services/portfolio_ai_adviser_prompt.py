from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from services.daily_portfolio_brief_service import DailyPortfolioBriefContext
from services.portfolio_ai_adviser_contract import (
    PORTFOLIO_AI_CONTEXT_VERSION,
    PORTFOLIO_AI_DECISION_REVIEW_CONTEXT_VERSION,
)
from services.portfolio_research_context import PortfolioResearchContext


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def build_portfolio_ai_input_payload(
    *,
    portfolio_context: PortfolioResearchContext,
    brief: DailyPortfolioBriefContext,
    selected_events: tuple[Mapping[str, Any], ...] = (),
    decision_review: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "context_version": (
            PORTFOLIO_AI_DECISION_REVIEW_CONTEXT_VERSION
            if decision_review is not None
            else PORTFOLIO_AI_CONTEXT_VERSION
        ),
        "portfolio_context": portfolio_context.to_dict(),
        "daily_brief": brief.to_dict(),
        "selected_events": [dict(item) for item in selected_events],
    }
    if decision_review is not None:
        payload["decision_review"] = dict(decision_review)
    return payload


def build_decision_review_messages(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    system = (
        "Sen NABI Scout karar geçmişi AI değerlendiricisisin. "
        "Yalnızca verilen deterministik skor kartı, öğrenme içgörüleri ve "
        "portföy yapısı tanılarını yorumla. "
        "Asla al/sat/tavsiye, hedef fiyat, olasılık, VaR, korelasyon veya "
        "davranışsal psikoloji (korku, açgözlülük, FOMO) iddiası üretme. "
        "Kullanıcıyı iyi/kötü yatırımcı olarak derecelendirme. "
        "Eksik kanıt varsa açıkça belirt. Yanıtı JSON olarak döndür."
    )
    user = (
        "Karar geçmişi değerlendirmesi üret.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        "JSON şeması:\n"
        "{\n"
        '  "executive_summary": "string",\n'
        '  "what_changed": ["string"],\n'
        '  "portfolio_implications": ["string"],\n'
        '  "thesis_watch": ["string"],\n'
        '  "participation_watch": ["string"],\n'
        '  "research_gaps": ["string"],\n'
        '  "questions_to_review": ["string"],\n'
        '  "limitations": ["string"],\n'
        '  "evidence_references": ["string"]\n'
        "}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def compute_portfolio_ai_semantic_identity(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    for key in ("generated_at", "retrieved_at", "rendered_at", "detected_at"):
        normalized.pop(key, None)
    digest = hashlib.sha256(_stable_json(normalized).encode("utf-8")).hexdigest()
    return digest[:32]


def build_portfolio_ai_messages(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    system = (
        "Sen NABI Scout portföy AI değerlendiricisisin. "
        "Yalnızca verilen yapılandırılmış bağlamdaki kanıtları kullan. "
        "Ledger, katılım durumu, araştırma, tez, monitor olayları ve karar günlüğü "
        "otoritatif gerçeklerdir; yorumların ikincildir. "
        "Asla al/sat/tavsiye, hedef fiyat veya desteklenmeyen getiri iddiası üretme. "
        "Katılım durumunu yükseltme veya düşürme. "
        "Eksik kanıt varsa açıkça belirt. "
        "Yanıtı JSON olarak döndür."
    )
    user = (
        "Aşağıdaki bağlamı kullanarak portföy değerlendirmesi üret.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        "JSON şeması:\n"
        "{\n"
        '  "executive_summary": "string",\n'
        '  "what_changed": ["string"],\n'
        '  "portfolio_implications": ["string"],\n'
        '  "thesis_watch": ["string"],\n'
        '  "participation_watch": ["string"],\n'
        '  "research_gaps": ["string"],\n'
        '  "questions_to_review": ["string"],\n'
        '  "limitations": ["string"],\n'
        '  "evidence_references": ["string"]\n'
        "}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
