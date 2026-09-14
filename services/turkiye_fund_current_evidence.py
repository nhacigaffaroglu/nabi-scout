"""Canonical current-evidence policy for Türkiye fund research.

Quarantines cached KAP evidence whose disclosure identity no longer matches
the current official fund identity.

Pure/read-only policy:
- no network access
- no cache writes
- no production persistence
- no ranking/decision/allocation/execution
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def filter_current_packs(
    packs: Mapping[str, Mapping[str, Any]],
    identities: Sequence[Any],
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    """Return current evidence packs and stale-pack quarantine codes.

    A pack is usable only when its fund exists in the supplied current
    identity set. Pilot-frozen fixtures remain explicitly allowed.

    When the current identity has a non-zero KAP disclosure index, the
    evidence pack must carry the same index; otherwise it is quarantined.
    """

    by_code = {
        str(row.fund_code).strip().upper(): row
        for row in identities
        if str(getattr(row, "fund_code", "") or "").strip()
    }

    current: dict[str, dict[str, Any]] = {}
    quarantined: list[str] = []

    for raw_code, raw in packs.items():
        code = str(raw_code).strip().upper()
        if not code:
            continue

        pack = dict(raw)
        identity = by_code.get(code)

        if identity is None:
            continue

        if pack.get("pilot_frozen"):
            current[code] = pack
            continue

        expected = int(getattr(identity, "kap_disclosure_index", 0) or 0)
        actual = int(pack.get("kap_disclosure_index") or 0)

        if expected and actual != expected:
            quarantined.append(code)
            continue

        current[code] = pack

    return current, tuple(sorted(quarantined))
