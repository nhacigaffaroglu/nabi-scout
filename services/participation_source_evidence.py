from __future__ import annotations

from typing import Any, Mapping, Tuple, Union

SourceEvidencePairs = Tuple[Tuple[str, str], ...]
SourceEvidenceValue = Union[SourceEvidencePairs, Mapping[str, Any], None]


def participation_source_evidence_mapping(
    source_evidence: SourceEvidenceValue,
) -> dict[str, str]:
    """Normalize participation provenance evidence to a string mapping.

    Production ``ParticipationAssessmentResult.source_evidence`` is an immutable
    tuple of ``(key, value)`` provenance pairs (e.g. ``("provider", "SEC")``).
    Persisted snapshots may already be JSON objects.
    """
    if not source_evidence:
        return {}
    if isinstance(source_evidence, Mapping):
        return {str(key): str(value) for key, value in source_evidence.items()}
    return dict(source_evidence)


def source_evidence_get(
    source_evidence: SourceEvidenceValue,
    key: str,
    default: str = "",
) -> str:
    return participation_source_evidence_mapping(source_evidence).get(key, default)
