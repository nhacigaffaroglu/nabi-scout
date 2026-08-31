"""Extract canonical mandate / governance excerpts from official KAP text.

Token set matches accepted Participation methodology. Capture does not
loosen Uygun. Name/umbrella alone still cannot produce Uygun.
"""

from __future__ import annotations

import re
from typing import Sequence

from services.official_kap_pdr import _fold

MANDATE_TOKENS = (
    "katılım fonu statüsündedir",
    "katılım prensiplerine uygunluğu esas",
    "faizsiz/katılım finans ilkelerine uygun",
    "portföy yönetiminde katılım prensiplerine uygunluk",
    "kira sertifikaları",
)

# Capture-only. Uygun still requires the accepted governance tokens below.
GOVERNANCE_CAPTURE_TOKENS = (
    "danışma komitesi",
    "danışma kurulu",
    "icazet belgesi",
    "katılım esasları",
    "faizsiz finans",
    "faizsiz/katılım",
)

GOVERNANCE_UYGUN_TOKENS = (
    "danışma komitesi",
    "danışma kurulu",
    "icazet belgesi",
)

PURIFICATION_TOKENS = (
    "arındırıl",
    "mahzurlu gelir",
    "temizleme",
    "purification",
    "icazet belgesi gider",
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> tuple[str, ...]:
    parts = [re.sub(r"\s+", " ", part).strip(" \t-•") for part in _SENTENCE.split(str(text or ""))]
    return tuple(part for part in parts if len(part) >= 12)


def excerpts_for_tokens(text: str, tokens: Sequence[str], *, limit: int = 8) -> tuple[str, ...]:
    folded_tokens = tuple(_fold(token) for token in tokens)
    found: list[str] = []
    for sentence in _sentences(text):
        blob = _fold(sentence)
        if any(token in blob for token in folded_tokens):
            if sentence not in found:
                found.append(sentence)
        if len(found) >= limit:
            break
    return tuple(found)


def extract_mandate_excerpts(*texts: str) -> tuple[str, ...]:
    return excerpts_for_tokens("\n".join(texts), MANDATE_TOKENS)


def extract_governance_excerpts(*texts: str) -> tuple[str, ...]:
    return excerpts_for_tokens("\n".join(texts), GOVERNANCE_CAPTURE_TOKENS)


def extract_purification_excerpts(*texts: str) -> tuple[str, ...]:
    return excerpts_for_tokens("\n".join(texts), PURIFICATION_TOKENS)


def governance_uygun_tokens_present(excerpts: Sequence[str]) -> bool:
    blob = _fold(" ".join(excerpts))
    return any(token in blob for token in GOVERNANCE_UYGUN_TOKENS)
