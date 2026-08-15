from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from services.company_intelligence_constants import NEWS_MATERIALITY_RECENT_DAYS, PROVIDER_NAME
from services.company_intelligence_earnings_calendar import build_earnings_catalysts
from services.company_intelligence_contract import (
    CatalystItem,
    IntelligenceProvenance,
    NewsEvent,
    NewsSection,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import headlines_similar, normalize_headline, normalize_url, strip_html


_CATEGORY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("EARNINGS", ("earnings", "quarter", "results", "kazanç", "finansal sonuç")),
    ("GUIDANCE", ("guidance", "outlook", "forecast", "beklenti")),
    ("M_AND_A", ("acquire", "merger", "acquisition", "satın al", "birleşme")),
    ("REGULATORY", ("regulator", "sec", "fda", "regülasyon")),
    ("LEGAL", ("lawsuit", "court", "legal", "dava")),
    ("MANAGEMENT", ("ceo", "cfo", "executive", "yönetim", "appoint")),
    ("CAPITAL_ALLOCATION", ("buyback", "repurchase", "dividend", "temettü")),
    ("PRODUCT", ("launch", "product", "ürün")),
    ("PARTNERSHIP", ("partner", "partnership", "iş ortak")),
)


def _classify_event(headline: str, summary: str) -> Tuple[str, str]:
    text = f"{headline} {summary}".lower()
    for category, keywords in _CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category, "MEDIUM"
    return "OTHER", "LOW"


def _materiality(category: str, headline: str, published_at: Optional[str]) -> str:
    if category in {"EARNINGS", "GUIDANCE", "M_AND_A", "REGULATORY", "LEGAL", "MANAGEMENT"}:
        return "MATERIAL"
    if category in {"CAPITAL_ALLOCATION", "PRODUCT", "PARTNERSHIP"}:
        return "RELEVANT"
    recent = False
    if published_at:
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - published).days
            recent = age_days <= NEWS_MATERIALITY_RECENT_DAYS
        except ValueError:
            recent = False
    if recent and category != "OTHER":
        return "RELEVANT"
    return "NOISE"


def _impact_domains(category: str) -> Tuple[str, ...]:
    mapping = {
        "EARNINGS": ("REVENUE", "OPERATING_MARGIN", "FREE_CASH_FLOW"),
        "GUIDANCE": ("REVENUE", "OPERATING_MARGIN"),
        "M_AND_A": ("BALANCE_SHEET", "COMPETITIVE_POSITION"),
        "REGULATORY": ("REGULATORY_RISK",),
        "LEGAL": ("LEGAL_RISK",),
        "MANAGEMENT": ("MANAGEMENT",),
        "CAPITAL_ALLOCATION": ("SHARE_COUNT", "FREE_CASH_FLOW"),
        "PRODUCT": ("REVENUE", "COMPETITIVE_POSITION"),
        "PARTNERSHIP": ("REVENUE", "SUPPLY_CHAIN"),
    }
    return mapping.get(category, ("UNKNOWN",))


def _event_id(article: dict) -> str:
    for key in ("id", "uuid", "articleId"):
        value = article.get(key)
        if value:
            return str(value)
    url = normalize_url(str(article.get("url") or ""))
    headline = normalize_headline(str(article.get("title") or article.get("headline") or ""))
    digest = hashlib.sha256(f"{url}|{headline}".encode("utf-8")).hexdigest()[:16]
    return f"news-{digest}"


def _dedupe_articles(articles: List[dict]) -> Tuple[List[dict], int]:
    kept: List[dict] = []
    seen_urls: Set[str] = set()
    seen_headlines: List[str] = []
    removed = 0
    for article in articles:
        url = normalize_url(str(article.get("url") or ""))
        headline = str(article.get("title") or article.get("headline") or "").strip()
        if url and url in seen_urls:
            removed += 1
            continue
        if any(headlines_similar(headline, existing) for existing in seen_headlines):
            removed += 1
            continue
        if url:
            seen_urls.add(url)
        if headline:
            seen_headlines.append(headline)
        kept.append(article)
    return kept, removed


def build_news_intelligence(bundle: CompanyProviderBundle) -> NewsSection:
    deduped, removed = _dedupe_articles(bundle.news or [])
    events: List[NewsEvent] = []
    for article in deduped:
        headline = str(article.get("title") or article.get("headline") or "").strip()
        if not headline:
            continue
        summary = strip_html(str(article.get("text") or article.get("summary") or ""))[:500] or None
        category, confidence = _classify_event(headline, summary or "")
        published_at = article.get("publishedDate") or article.get("published_at")
        events.append(
            NewsEvent(
                event_id=_event_id(article),
                symbol=bundle.symbol,
                headline=headline,
                source=article.get("site") or article.get("source"),
                published_at=str(published_at) if published_at else None,
                url=article.get("url"),
                summary=summary,
                category=category,
                materiality=_materiality(category, headline, str(published_at) if published_at else None),
                sentiment=article.get("sentiment") or article.get("sentimentScore"),
                impact_domains=_impact_domains(category),
                confidence=confidence,
                provenance=IntelligenceProvenance(
                    provider=PROVIDER_NAME,
                    data_family="stock_news",
                    retrieved_at=bundle.retrieved_at,
                ),
            )
        )

    events.sort(
        key=lambda item: item.materiality != "MATERIAL",
    )
    failures = tuple(item for item in bundle.failures if item.startswith("stock_news"))
    return NewsSection(
        events=tuple(events),
        dedupe_count=removed,
        provider_failures=failures,
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="stock_news",
            retrieved_at=bundle.retrieved_at,
        ),
    )


def build_catalysts(bundle: CompanyProviderBundle, news_events: Tuple[NewsEvent, ...]) -> Tuple[CatalystItem, ...]:
    items: List[CatalystItem] = []
    seen: Set[str] = set()

    for catalyst in build_earnings_catalysts(
        symbol=bundle.symbol,
        calendar_rows=list(bundle.earnings_calendar or []),
    ):
        if catalyst.code in seen:
            continue
        seen.add(catalyst.code)
        items.append(catalyst)

    for event in news_events:
        if event.materiality not in {"MATERIAL", "THESIS_RELEVANT"}:
            continue
        if event.category not in {"EARNINGS", "M_AND_A", "REGULATORY", "MANAGEMENT", "GUIDANCE"}:
            continue
        key = f"news-{event.event_id}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            CatalystItem(
                code=key,
                catalyst_type=event.category,
                date=event.published_at,
                description=event.headline,
                source=event.source or PROVIDER_NAME,
                confidence=event.confidence,
                status="RECENT" if event.published_at else "UNKNOWN",
                related_symbols=(bundle.symbol,),
            )
        )
    return tuple(items)
