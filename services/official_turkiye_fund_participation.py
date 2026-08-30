"""Deterministic Turkish fund Participation methodology.

Official evidence only. Fund name / umbrella type cannot produce Uygun.
Does not score Fund Intelligence. Does not run 8E or New Money.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional

from services.fund_product_contract import (
    ASSET_GROUP_CASH,
    ASSET_GROUP_EQUITY,
    ASSET_GROUP_FUND,
    ASSET_GROUP_LEASE_CERTIFICATE,
    ASSET_GROUP_OTHER,
    ASSET_GROUP_PARTICIPATION_ACCOUNT,
    ASSET_GROUP_REPO,
    AUTHORITY_KAP,
    AUTHORITY_SPK,
    AUTHORITY_TKBB,
    EVIDENCE_TYPE_GOVERNANCE,
    EVIDENCE_TYPE_HOLDINGS,
    EVIDENCE_TYPE_ICAZET,
    EVIDENCE_TYPE_MANDATE,
    EVIDENCE_TYPE_PURIFICATION,
    EVIDENCE_TYPE_REGULATORY_FRAMEWORK,
    FRAMEWORK_TURKIYE_PARTICIPATION,
    FRESHNESS_ACCEPTABLE,
    FRESHNESS_STALE,
    GOVERNANCE_CONFIRMED,
    GOVERNANCE_CONFLICT,
    GOVERNANCE_MISSING,
    GOVERNANCE_PARTIAL,
    HOLDINGS_COMPLIANT,
    HOLDINGS_MISSING,
    HOLDINGS_REVIEW,
    IDENTITY_RESOLVED,
    MANDATE_CONFIRMED,
    MANDATE_UNRESOLVED,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
    OfficialParticipationEvidenceItem,
    PILOT_TEFAS_FUND_CODES,
    PROVIDER_KAP_FUND,
    PURIFICATION_MISSING,
    PURIFICATION_NOT_REQUIRED,
    PURIFICATION_POLICY_ONLY,
    TurkiyeFundParticipationVerdict,
    TurkiyeParticipationFramework,
)
from services.official_kap_pdr import asset_group_weights, join_pdr_to_security_master
from services.official_kap_pdr_evidence import load_captured_pdr_holdings
from services.official_tefas import normalize_fund_code
from services.official_turkiye_fund_evidence import EVIDENCE_DIR
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)

FRAMEWORK_PATH = EVIDENCE_DIR / "turkiye_participation_framework.json"
PDR_MAX_AGE_DAYS = 180
SPK_EXEMPT_GROUPS = frozenset(
    {ASSET_GROUP_LEASE_CERTIFICATE, ASSET_GROUP_PARTICIPATION_ACCOUNT, ASSET_GROUP_REPO}
)
AIS_ALLOWED = SPK_EXEMPT_GROUPS
ZPE_ALLOWED = frozenset(
    {ASSET_GROUP_EQUITY, ASSET_GROUP_FUND, ASSET_GROUP_PARTICIPATION_ACCOUNT, ASSET_GROUP_REPO}
)
IAT_ALLOWED = frozenset({ASSET_GROUP_LEASE_CERTIFICATE, ASSET_GROUP_CASH, ASSET_GROUP_OTHER})

# Verdict policy — defined before pilot evaluation.
# UYGUN requires ALL of the following. Missing evidence is Kontrol Et, never Uygun Değil.
UYGUN_REQUIREMENTS = (
    "valid_deterministic_turkish_fund_identity",
    "applicable_spk_regulatory_framework",
    "explicit_fund_specific_participation_mandate",
    "governance_or_equivalent_approval_confirmed",
    "latest_official_holdings_available",
    "no_material_contradiction",
    "evidence_freshness_acceptable",
)


def load_participation_bundle(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads((path or FRAMEWORK_PATH).read_text(encoding="utf-8"))


def turkiye_participation_framework(
    bundle: Optional[Mapping[str, Any]] = None,
) -> TurkiyeParticipationFramework:
    raw = dict((bundle or load_participation_bundle()).get("framework") or {})
    return TurkiyeParticipationFramework(
        framework_id=str(raw.get("framework_id") or FRAMEWORK_TURKIYE_PARTICIPATION),
        title=str(raw.get("title") or ""),
        authority=AUTHORITY_SPK,
        version=str(raw.get("version") or ""),
        as_of=str(raw.get("as_of") or "") or None,
        source_url=str(raw.get("source_url") or ""),
        provenance=tuple(raw.get("provenance") or ()),
        summary=str(raw.get("summary") or ""),
        excerpts=tuple(raw.get("excerpts") or ()),
    )


def tkbb_framework(bundle: Optional[Mapping[str, Any]] = None) -> TurkiyeParticipationFramework:
    raw = dict((bundle or load_participation_bundle()).get("tkbb") or {})
    return TurkiyeParticipationFramework(
        framework_id=str(raw.get("framework_id") or "TKBB_DANISMA_KURULU"),
        title=str(raw.get("title") or ""),
        authority=AUTHORITY_TKBB,
        version=str(raw.get("version") or ""),
        as_of=str(raw.get("as_of") or "") or None,
        source_url=str(raw.get("source_url") or ""),
        provenance=tuple(raw.get("provenance") or ()),
        summary=str(raw.get("summary") or ""),
        excerpts=tuple(raw.get("excerpts") or ()),
    )


def _item(
    *,
    fund_code: Optional[str],
    source: str,
    title: str,
    document_date: Optional[str],
    evidence_type: str,
    raw_text: str,
    source_url: str,
    provenance: tuple[str, ...],
    reliability: str = "HIGH",
    applies_to_fund: bool = True,
) -> OfficialParticipationEvidenceItem:
    return OfficialParticipationEvidenceItem(
        fund_code=fund_code,
        source=source,
        document_title=title,
        document_date=document_date,
        document_version=None,
        evidence_type=evidence_type,
        raw_text=raw_text,
        source_url=source_url,
        provenance=provenance,
        reliability=reliability,
        applies_to_fund=applies_to_fund,
    )


def mandate_from_name_only(official_name: str) -> str:
    """Katılım in the fund name is discovery only."""
    _ = official_name
    return MANDATE_UNRESOLVED


def mandate_from_umbrella_only(umbrella_type: str) -> str:
    """Katılım Şemsiye Fonu alone is not a fund-specific mandate."""
    _ = umbrella_type
    return MANDATE_UNRESOLVED


def _explicit_mandate(excerpts: tuple[str, ...]) -> bool:
    blob = " ".join(excerpts).casefold()
    return any(
        token in blob
        for token in (
            "katılım fonu statüsündedir",
            "katılım prensiplerine uygunluğu esas",
            "faizsiz/katılım finans ilkelerine uygun",
            "portföy yönetiminde katılım prensiplerine uygunluk",
            "kira sertifikaları",
        )
    ) and "katılım" in blob


def _explicit_governance(excerpts: tuple[str, ...]) -> bool:
    blob = " ".join(excerpts).casefold()
    return any(
        token in blob
        for token in (
            "danışma komitesi",
            "danışma kurulu",
            "icazet belgesi",
        )
    )


def _holdings_state(fund_code: str) -> tuple[str, tuple[str, ...], tuple[OfficialParticipationEvidenceItem, ...]]:
    file = load_captured_pdr_holdings(fund_code)
    if file is None or not file.holdings:
        return HOLDINGS_MISSING, ("OFFICIAL_PDR_MISSING",), ()
    groups = asset_group_weights(file)
    reasons: list[str] = []
    if not file.weights.weight_reconciled:
        reasons.append("PDR_WEIGHTS_UNRECONCILED")
    unknown = {name: weight for name, weight in groups.items() if name not in _allowed(fund_code)}
    if unknown:
        reasons.append("HOLDING_GROUP_OUTSIDE_MANDATE:" + ",".join(sorted(unknown)))
    if fund_code == "AIS":
        if groups.get(ASSET_GROUP_PARTICIPATION_ACCOUNT, 0.0) > 50.0:
            reasons.append("AIS_KATILMA_OVER_50")
    if fund_code == "ZPE":
        sleeve = groups.get(ASSET_GROUP_EQUITY, 0.0) + _xk_tracking_fund_weight(file)
        if sleeve < 80.0:
            reasons.append("ZPE_XK_SLEEVE_BELOW_80")
        overlap = join_pdr_to_security_master(file)
        _ = overlap  # exact SM overlap is supporting, not required
    if fund_code == "IAT":
        if groups.get(ASSET_GROUP_LEASE_CERTIFICATE, 0.0) < 80.0:
            reasons.append("IAT_KIRA_BELOW_80")
        other = groups.get(ASSET_GROUP_OTHER, 0.0)
        if other > 0.5:
            reasons.append("IAT_OTHER_POSITIVE_WEIGHT")
    item = _item(
        fund_code=fund_code,
        source=PROVIDER_KAP_FUND,
        title=f"KAP Portföy Dağılım Raporu {file.report_period or ''}".strip(),
        document_date=file.report_date or file.report_period,
        evidence_type=EVIDENCE_TYPE_HOLDINGS,
        raw_text=f"groups={groups} reconciled={file.weights.weight_reconciled}",
        source_url=file.source_url,
        provenance=(PROVIDER_KAP_FUND, "official_pdr", file.report_period or ""),
    )
    if reasons:
        return HOLDINGS_REVIEW, tuple(reasons), (item,)
    return HOLDINGS_COMPLIANT, (), (item,)


def _allowed(fund_code: str) -> frozenset[str]:
    if fund_code == "AIS":
        return AIS_ALLOWED
    if fund_code == "ZPE":
        return ZPE_ALLOWED
    if fund_code == "IAT":
        return IAT_ALLOWED
    return frozenset()


def _xk_tracking_fund_weight(file) -> float:
    """Official PDR codes that are XK030/XK100 trackers. No name-inferred Sharia."""
    total = 0.0
    for row in file.holdings:
        code = str(row.official_code or "").upper()
        if row.asset_group == ASSET_GROUP_FUND and code in {"Z30KE.F", "Z30KP.F"}:
            total += float(row.portfolio_weight or 0.0)
    return round(total, 4)


def _freshness(fund_code: str, row: Mapping[str, Any], *, as_of: date) -> str:
    file = load_captured_pdr_holdings(fund_code)
    if file is None or not (file.report_period or file.report_date):
        return FRESHNESS_STALE
    period = file.report_period or (file.report_date or "")[:7]
    try:
        year, month = int(period[:4]), int(period[5:7])
        pdr_day = date(year, month, 1)
    except (TypeError, ValueError):
        return FRESHNESS_STALE
    if (as_of - pdr_day).days > PDR_MAX_AGE_DAYS:
        return FRESHNESS_STALE
    _ = row
    return FRESHNESS_ACCEPTABLE


def _purification_state(fund_code: str, excerpts: tuple[str, ...]) -> str:
    if excerpts:
        return PURIFICATION_POLICY_ONLY
    if fund_code in {"AIS", "IAT"}:
        return PURIFICATION_NOT_REQUIRED
    return PURIFICATION_MISSING


def evaluate_turkiye_fund_participation(
    symbol: str,
    *,
    identity_status: Optional[str] = None,
    official_name: Optional[str] = None,
    umbrella_type: Optional[str] = None,
    as_of: Optional[date] = None,
    bundle: Optional[Mapping[str, Any]] = None,
    name_only: bool = False,
    umbrella_only: bool = False,
    forced_governance: Optional[str] = None,
    forced_contradiction: Optional[tuple[str, ...]] = None,
) -> TurkiyeFundParticipationVerdict:
    """Canonical verdict. Name/umbrella-only paths cannot emit Uygun."""
    code = normalize_fund_code(symbol)
    day = as_of or date(2026, 8, 30)
    payload = bundle or load_participation_bundle()
    framework = turkiye_participation_framework(payload)
    fund_row = dict((payload.get("funds") or {}).get(code) or {})
    evidence: list[OfficialParticipationEvidenceItem] = [
        _item(
            fund_code=None,
            source=AUTHORITY_SPK,
            title=framework.title,
            document_date=framework.as_of,
            evidence_type=EVIDENCE_TYPE_REGULATORY_FRAMEWORK,
            raw_text=framework.excerpts[0] if framework.excerpts else framework.summary,
            source_url=framework.source_url,
            provenance=framework.provenance,
            applies_to_fund=False,
        )
    ]
    mandate_excerpts = tuple(fund_row.get("mandate_excerpts") or ())
    governance_excerpts = tuple(fund_row.get("governance_excerpts") or ())
    purification_excerpts = tuple(fund_row.get("purification_excerpts") or ())
    izahname_url = str(fund_row.get("izahname_url") or "")
    izahname_date = str(fund_row.get("izahname_date") or "") or None

    if name_only:
        mandate = mandate_from_name_only(official_name or "")
        return TurkiyeFundParticipationVerdict(
            fund_code=code,
            identity_resolved=identity_status == IDENTITY_RESOLVED,
            framework_applicable=True,
            mandate_state=mandate,
            governance_state=GOVERNANCE_MISSING,
            icazet_present=False,
            equivalent_approval_reason=None,
            holdings_state=HOLDINGS_MISSING,
            contradiction=False,
            contradiction_reasons=(),
            purification_state=PURIFICATION_MISSING,
            purification_policy_present=False,
            purification_factor_pct=None,
            freshness=FRESHNESS_STALE,
            participation_status=PARTICIPATION_STATUS_KONTROL_ET,
            research_allowed=False,
            theoretically_publishable=False,
            blockers=("NAME_ALONE_INSUFFICIENT",),
            evidence=tuple(evidence),
        )
    if umbrella_only:
        return TurkiyeFundParticipationVerdict(
            fund_code=code,
            identity_resolved=identity_status == IDENTITY_RESOLVED,
            framework_applicable=True,
            mandate_state=mandate_from_umbrella_only(umbrella_type or ""),
            governance_state=GOVERNANCE_MISSING,
            icazet_present=False,
            equivalent_approval_reason=None,
            holdings_state=HOLDINGS_MISSING,
            contradiction=False,
            contradiction_reasons=(),
            purification_state=PURIFICATION_MISSING,
            purification_policy_present=False,
            purification_factor_pct=None,
            freshness=FRESHNESS_STALE,
            participation_status=PARTICIPATION_STATUS_KONTROL_ET,
            research_allowed=False,
            theoretically_publishable=False,
            blockers=("UMBRELLA_ALONE_INSUFFICIENT",),
            evidence=tuple(evidence),
        )

    for text in mandate_excerpts:
        evidence.append(
            _item(
                fund_code=code,
                source=AUTHORITY_KAP,
                title="KAP izahname / YBF mandate",
                document_date=izahname_date,
                evidence_type=EVIDENCE_TYPE_MANDATE,
                raw_text=text,
                source_url=izahname_url,
                provenance=(PROVIDER_KAP_FUND, "izahname_ybf"),
            )
        )
    for text in governance_excerpts:
        evidence.append(
            _item(
                fund_code=code,
                source=AUTHORITY_KAP,
                title="KAP izahname governance",
                document_date=izahname_date,
                evidence_type=EVIDENCE_TYPE_GOVERNANCE,
                raw_text=text,
                source_url=izahname_url,
                provenance=(PROVIDER_KAP_FUND, "izahname"),
            )
        )

    identity_ok = identity_status == IDENTITY_RESOLVED if identity_status is not None else True
    mandate = MANDATE_CONFIRMED if _explicit_mandate(mandate_excerpts) else MANDATE_UNRESOLVED
    if forced_governance:
        governance = forced_governance
        equivalent = None
    elif _explicit_governance(governance_excerpts) and mandate == MANDATE_CONFIRMED:
        governance = GOVERNANCE_CONFIRMED
        equivalent = (
            "KAP izahname defines a fund-specific Danışma Komitesi / İcazet Belgesi "
            "that binds portfolio construction. SPK Rehber 1.6 recognizes this approval "
            "mechanism. A separate downloadable icazet PDF was not located."
        )
    elif _explicit_governance(governance_excerpts):
        governance = GOVERNANCE_PARTIAL
        equivalent = None
    else:
        governance = GOVERNANCE_MISSING
        equivalent = None
    icazet_url = fund_row.get("icazet_document_url")
    icazet_present = bool(icazet_url)
    if icazet_present:
        evidence.append(
            _item(
                fund_code=code,
                source=AUTHORITY_KAP,
                title="Official icazet document",
                document_date=izahname_date,
                evidence_type=EVIDENCE_TYPE_ICAZET,
                raw_text=str(icazet_url),
                source_url=str(icazet_url),
                provenance=(PROVIDER_KAP_FUND, "icazet"),
            )
        )

    holdings_state, holding_reasons, holding_items = _holdings_state(code)
    evidence.extend(holding_items)
    contradiction_reasons = tuple(forced_contradiction or holding_reasons)
    contradiction = bool(forced_contradiction) or (
        holdings_state == HOLDINGS_REVIEW
        and any(
            item.startswith("HOLDING_GROUP_OUTSIDE_MANDATE") or "CONFLICT" in item
            for item in holding_reasons
        )
    )
    if governance == GOVERNANCE_CONFLICT:
        contradiction = True
        contradiction_reasons = contradiction_reasons + ("GOVERNANCE_CONFLICT",)

    purification = _purification_state(code, purification_excerpts)
    if purification_excerpts:
        evidence.append(
            _item(
                fund_code=code,
                source=AUTHORITY_KAP,
                title="KAP izahname purification/icazet expense",
                document_date=izahname_date,
                evidence_type=EVIDENCE_TYPE_PURIFICATION,
                raw_text=purification_excerpts[0],
                source_url=izahname_url,
                provenance=(PROVIDER_KAP_FUND, "izahname"),
            )
        )
    freshness = _freshness(code, fund_row, as_of=day)

    blockers: list[str] = []
    if not identity_ok:
        blockers.append("IDENTITY_UNRESOLVED")
    if not framework.framework_id:
        blockers.append("FRAMEWORK_MISSING")
    if mandate != MANDATE_CONFIRMED:
        blockers.append("MANDATE_UNRESOLVED")
    if governance != GOVERNANCE_CONFIRMED:
        blockers.append("GOVERNANCE_NOT_CONFIRMED")
    if holdings_state == HOLDINGS_MISSING:
        blockers.append("HOLDINGS_MISSING")
    if contradiction:
        blockers.append("MATERIAL_CONTRADICTION")
    if holdings_state == HOLDINGS_REVIEW:
        blockers.extend(holding_reasons)
    if freshness != FRESHNESS_ACCEPTABLE:
        blockers.append("EVIDENCE_STALE")

    status = PARTICIPATION_STATUS_KONTROL_ET
    if contradiction and any("ADVERSE" in item or "UYGUN_DEGIL" in item for item in contradiction_reasons):
        status = PARTICIPATION_STATUS_UYGUN_DEGIL
    elif not blockers:
        status = PARTICIPATION_STATUS_UYGUN

    research = status == PARTICIPATION_STATUS_UYGUN
    return TurkiyeFundParticipationVerdict(
        fund_code=code,
        identity_resolved=identity_ok,
        framework_applicable=True,
        mandate_state=mandate,
        governance_state=governance,
        icazet_present=icazet_present,
        equivalent_approval_reason=equivalent if governance == GOVERNANCE_CONFIRMED else None,
        holdings_state=holdings_state,
        contradiction=contradiction,
        contradiction_reasons=contradiction_reasons,
        purification_state=purification,
        purification_policy_present=bool(purification_excerpts),
        purification_factor_pct=None,
        freshness=freshness,
        participation_status=status,
        research_allowed=research,
        theoretically_publishable=research,
        blockers=tuple(dict.fromkeys(blockers)),
        evidence=tuple(evidence),
    )


def evaluate_pilot_participation(
    symbol: str,
    *,
    as_of: Optional[date] = None,
) -> TurkiyeFundParticipationVerdict:
    from services.official_tefas_product import default_tefas_fund_provider

    provider = default_tefas_fund_provider()
    identity = provider.turkiye_identity(symbol)
    kap = provider.kap_mandate(symbol)
    return evaluate_turkiye_fund_participation(
        symbol,
        identity_status=identity.identity_status,
        official_name=identity.official_name,
        umbrella_type=kap.umbrella_type,
        as_of=as_of,
    )


def theoretical_publishability(symbol: str) -> bool:
    """FI publishable boundary only. Does not persist a snapshot."""
    verdict = evaluate_pilot_participation(symbol)
    if verdict.participation_status != PARTICIPATION_STATUS_UYGUN:
        return False
    from services.fund_intelligence_engine import evaluate_official_fund_intelligence

    view = evaluate_official_fund_intelligence(symbol)
    return bool(view.publishable)


def supported_participation_pilots() -> tuple[str, ...]:
    return PILOT_TEFAS_FUND_CODES
