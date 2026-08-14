from __future__ import annotations

SCREENING_CONTEXT_NEW_ENTRY = "NEW_ENTRY"
SCREENING_CONTEXT_EXISTING_CONSTITUENT = "EXISTING_CONSTITUENT"
SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP = "UNKNOWN_MEMBERSHIP"

DEFAULT_EQUITY_SCREENING_CONTEXT = SCREENING_CONTEXT_NEW_ENTRY

VALID_SCREENING_CONTEXTS = frozenset(
    {
        SCREENING_CONTEXT_NEW_ENTRY,
        SCREENING_CONTEXT_EXISTING_CONSTITUENT,
        SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP,
    }
)


def normalize_screening_context(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in VALID_SCREENING_CONTEXTS:
        return normalized
    return SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP


def resolve_threshold_context(screening_context: str) -> str:
    """Map screening context to the threshold tier used by the financial engine."""
    context = normalize_screening_context(screening_context)
    if context == SCREENING_CONTEXT_EXISTING_CONSTITUENT:
        return SCREENING_CONTEXT_EXISTING_CONSTITUENT
    if context == SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP:
        return SCREENING_CONTEXT_NEW_ENTRY
    return SCREENING_CONTEXT_NEW_ENTRY


def screening_context_label_tr(context: str) -> str:
    labels = {
        SCREENING_CONTEXT_NEW_ENTRY: "Yeni aday (giriş eşiği)",
        SCREENING_CONTEXT_EXISTING_CONSTITUENT: "Mevcut endeks bileşeni (finansal oran eşiği)",
        SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP: "Üyelik bilinmiyor (giriş eşiği uygulanır)",
    }
    return labels.get(normalize_screening_context(context), context)
