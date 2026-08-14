from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ParticipationCikResolution:
    cik: Optional[str]
    source: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)


def is_usable_cik(cik: Any) -> bool:
    if cik is None:
        return False
    text = str(cik).strip()
    if not text:
        return False
    digits = text.lstrip("0")
    if not digits:
        return False
    if not digits.isdigit():
        return False
    return True


def normalize_resolved_cik(cik: Any) -> Optional[str]:
    if not is_usable_cik(cik):
        return None
    text = str(cik).strip()
    return str(int(text))


def resolve_participation_cik(
    symbol: str,
    *,
    candidate_cik: Any = None,
    fmp_client: Any = None,
    sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> ParticipationCikResolution:
    normalized_symbol = str(symbol or "").strip().upper()
    warnings: list[str] = []

    if is_usable_cik(candidate_cik):
        return ParticipationCikResolution(
            cik=normalize_resolved_cik(candidate_cik),
            source="candidate_record",
        )

    if candidate_cik is not None and str(candidate_cik).strip():
        warnings.append(
            "Aday kaydındaki CIK geçersiz; alternatif kaynaklardan CIK aranıyor."
        )

    if fmp_client is not None:
        try:
            profile = fmp_client.profile(normalized_symbol) or {}
            fmp_cik = profile.get("cik")
            if is_usable_cik(fmp_cik):
                return ParticipationCikResolution(
                    cik=normalize_resolved_cik(fmp_cik),
                    source="fmp_profile",
                    warnings=tuple(dict.fromkeys(warnings)),
                )
        except Exception:
            warnings.append("FMP profilinden CIK alınamadı.")

    if sec_ticker_lookup:
        row = sec_ticker_lookup.get(normalized_symbol) or {}
        sec_cik = row.get("cik")
        if is_usable_cik(sec_cik):
            return ParticipationCikResolution(
                cik=normalize_resolved_cik(sec_cik),
                source="sec_ticker_lookup",
                warnings=tuple(dict.fromkeys(warnings)),
            )

    unresolved_warnings = tuple(
        dict.fromkeys(
            (
                *warnings,
                "SEC CIK çözümlenemedi; finansal katılım kanıtı alınamadı.",
            )
        )
    )
    return ParticipationCikResolution(
        cik=None,
        source="unresolved",
        warnings=unresolved_warnings,
    )
