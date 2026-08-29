"""Canonical Signal Intelligence service.

Single ingest / context entry. No provider calls. No SI score mutation.
Production persistence is disabled until the additive migration is applied.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from services.security_intelligence_contract import SecurityIntelligenceView
from services.signal_intelligence_contract import (
    SIGNAL_CONTRACT_VERSION,
    SIGNAL_ENGINE_VERSION,
    RawSignalInput,
    SignalEvidence,
    SignalEvent,
    SignalIntelligenceContext,
    SignalSnapshotRefs,
    empty_signal_context,
)
from services.signal_intelligence_engine import (
    build_context,
    build_event,
    build_evidence,
    compare_signal_state,
    event_identity,
    resolve_direction,
)
from services.signal_source_registry import resolve_source


@dataclass(frozen=True)
class IngestSignalResult:
    event: SignalEvent
    evidence: SignalEvidence
    created_event: bool
    created_evidence: bool
    replay_skipped: bool
    persisted: bool = False
    persistence_skipped: bool = True
    message: str = ""


class SignalIntelligenceService:
    def __init__(self, repo=None, *, persist_enabled: bool = False) -> None:
        self.repo = repo
        self.persist_enabled = persist_enabled

    def ingest(self, raw: RawSignalInput) -> IngestSignalResult:
        event_id = event_identity(raw)
        existing_event = self._get_event(event_id)
        extra_directions = []
        if existing_event is not None:
            extra_directions.append((existing_event.source_authority, existing_event.direction))
            source = resolve_source(raw.source_id, raw.source_type)
            extra_directions.append(
                (source.authority, resolve_direction(event_type=raw.event_type or existing_event.event_type, event_subtype=raw.event_subtype or existing_event.event_subtype))
            )
            raw = replace(
                raw,
                event_type=existing_event.event_type,
                event_subtype=existing_event.event_subtype or raw.event_subtype,
                factual_subject=existing_event.factual_subject or raw.factual_subject,
                headline=existing_event.headline or raw.headline,
                description=existing_event.description or raw.description,
                event_time=existing_event.event_time or raw.event_time,
                effective_time=existing_event.effective_time or raw.effective_time,
                security_id=existing_event.security_id or raw.security_id,
                raw_reference=existing_event.raw_reference or raw.raw_reference,
                authoritative_event_id=existing_event.authoritative_event_id or raw.authoritative_event_id,
                logical_event_key=existing_event.logical_event_key or raw.logical_event_key,
            )
        evidence = build_evidence(raw, event_id)
        existing_evidence = self._get_evidence(evidence.evidence_id)
        evidence_rows = [evidence]
        if existing_event is not None:
            for row in self._evidence_for_event(event_id):
                if row.evidence_id != evidence.evidence_id:
                    evidence_rows.append(row)
        event = build_event(raw, evidence_rows, extra_directions=extra_directions)
        created_evidence = existing_evidence is None
        created_event = existing_event is None
        write_event = created_event or (
            existing_event is not None and _event_core(existing_event) != _event_core(event)
        )
        write_evidence = created_evidence or (
            existing_evidence is not None and existing_evidence.to_dict() != evidence.to_dict()
        )
        identical = not write_event and not write_evidence
        persisted = False
        persistence_skipped = True
        if write_event:
            self._store_event(event)
        if write_evidence:
            self._store_evidence(evidence)
        if write_event or write_evidence:
            persisted, persistence_skipped = self._maybe_persist(event, evidence)
        message = (
            "Identical signal already present; write skipped."
            if identical
            else (
                "Signal stored in memory only; production persist disabled."
                if persistence_skipped
                else "Signal persisted."
            )
        )
        return IngestSignalResult(
            event=event,
            evidence=evidence,
            created_event=created_event and not identical,
            created_evidence=created_evidence and not identical,
            replay_skipped=identical,
            persisted=persisted,
            persistence_skipped=persistence_skipped,
            message=message,
        )

    def context_for(self, symbol: str) -> SignalIntelligenceContext:
        if self.repo is None:
            return empty_signal_context(symbol)
        events = []
        for row in self.repo.list_events(symbol):
            events.append(self._event_from_row(row))
        return build_context(symbol, events)

    def snapshot_refs(self, symbol: str) -> SignalSnapshotRefs:
        return self.context_for(symbol).snapshot_refs

    def attach_to_view(
        self,
        view: SecurityIntelligenceView,
        *,
        previous_refs: Optional[SignalSnapshotRefs] = None,
        mutate_change_flags: bool = False,
    ) -> SecurityIntelligenceView:
        context = self.context_for(view.symbol)
        flags = view.change_flags
        if mutate_change_flags:
            flags = tuple(
                dict.fromkeys(
                    (*view.change_flags, *compare_signal_state(previous_refs, context.snapshot_refs))
                )
            )
        return replace(view, signal_context=context, change_flags=flags)

    def _evidence_for_event(self, event_id: str) -> list[SignalEvidence]:
        if self.repo is None:
            return []
        return [self._evidence_from_row(row) for row in self.repo.list_evidence(event_id)]

    def _get_event(self, event_id: str) -> Optional[SignalEvent]:
        if self.repo is None:
            return None
        row = self.repo.get_event(event_id)
        return self._event_from_row(row) if row else None

    def _get_evidence(self, evidence_id: str) -> Optional[SignalEvidence]:
        if self.repo is None:
            return None
        row = self.repo.get_evidence(evidence_id)
        return self._evidence_from_row(row) if row else None

    def _store_event(self, event: SignalEvent) -> None:
        if self.repo is None:
            return
        payload = event.to_dict()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.repo.get_event(event.event_id) is None:
            payload["created_at"] = payload["updated_at"]
        self.repo.upsert_event(payload)

    def _store_evidence(self, evidence: SignalEvidence) -> None:
        if self.repo is None:
            return
        payload = evidence.to_dict()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.repo.get_evidence(evidence.evidence_id) is None:
            payload["created_at"] = payload["updated_at"]
        self.repo.upsert_evidence(payload)

    def _maybe_persist(self, event: SignalEvent, evidence: SignalEvidence) -> tuple[bool, bool]:
        if not self.persist_enabled:
            return False, True
        return False, True

    def _event_from_row(self, row: Mapping[str, Any]) -> SignalEvent:
        event = SignalEvent(
            event_id=str(row.get("event_id") or ""),
            symbol=str(row.get("symbol") or ""),
            security_id=row.get("security_id"),
            event_type=str(row.get("event_type") or ""),
            event_subtype=row.get("event_subtype"),
            headline=row.get("headline"),
            description=row.get("description"),
            event_time=row.get("event_time"),
            effective_time=row.get("effective_time"),
            source_authority=str(row.get("source_authority") or ""),
            verification_status=str(row.get("verification_status") or ""),
            materiality=str(row.get("materiality") or ""),
            direction=str(row.get("direction") or ""),
            strength=str(row.get("strength") or ""),
            reason_codes=tuple(row.get("reason_codes") or ()),
            evidence_ids=tuple(row.get("evidence_ids") or ()),
            factual_subject=row.get("factual_subject"),
            raw_reference=row.get("raw_reference"),
            as_of=row.get("as_of"),
            authoritative_event_id=row.get("authoritative_event_id"),
            logical_event_key=row.get("logical_event_key"),
            contract_version=str(row.get("contract_version") or SIGNAL_CONTRACT_VERSION),
            engine_version=str(row.get("engine_version") or SIGNAL_ENGINE_VERSION),
        )
        linked = tuple(item.evidence_id for item in self._evidence_for_event(event.event_id))
        if linked:
            event = replace(event, evidence_ids=linked)
        return event

    def _evidence_from_row(self, row: Mapping[str, Any]) -> SignalEvidence:
        return SignalEvidence(
            evidence_id=str(row.get("evidence_id") or ""),
            event_id=str(row.get("event_id") or ""),
            symbol=str(row.get("symbol") or ""),
            source_id=str(row.get("source_id") or ""),
            source_type=str(row.get("source_type") or ""),
            source_authority=str(row.get("source_authority") or ""),
            source_url=row.get("source_url"),
            external_id=row.get("external_id"),
            retrieved_at=row.get("retrieved_at"),
            as_of=row.get("as_of"),
            verification_status=str(row.get("verification_status") or ""),
            raw_reference=row.get("raw_reference"),
            headline=row.get("headline"),
            reason_codes=tuple(row.get("reason_codes") or ()),
            contract_version=str(row.get("contract_version") or SIGNAL_CONTRACT_VERSION),
            engine_version=str(row.get("engine_version") or SIGNAL_ENGINE_VERSION),
        )


def _event_core(event: SignalEvent) -> dict[str, Any]:
    payload = event.to_dict()
    payload.pop("evidence_ids", None)
    payload.pop("headline", None)
    payload.pop("description", None)
    return payload


def ingest_many(
    service: SignalIntelligenceService,
    rows: Sequence[RawSignalInput],
) -> tuple[IngestSignalResult, ...]:
    return tuple(service.ingest(row) for row in rows)
