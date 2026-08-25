"""Append-only, content-addressed SEC primary-filing cache.

Raw filing bytes are immutable. Replay uses stored bytes only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.sec_company_facts_evidence import canonical_json_dumps, pad_cik
from services.sec_filing_evidence import (
    CACHE_FORMAT_VERSION,
    SecFilingEvidence,
    SecFilingEvidenceCacheError,
    build_filing_evidence,
    verify_filing_digest,
)

DEFAULT_CACHE_ROOT = Path("data/private/sec_filings")
OBJECTS_DIRNAME = "objects"
ENVELOPES_DIRNAME = "envelopes"
MANIFEST_FILENAME = "manifest.json"


def default_sec_filing_cache_root() -> Path:
    return DEFAULT_CACHE_ROOT


class SecFilingEvidenceCache:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else default_sec_filing_cache_root()
        self.objects_dir = self.root / OBJECTS_DIRNAME
        self.envelopes_dir = self.root / ENVELOPES_DIRNAME
        self.manifest_path = self.root / MANIFEST_FILENAME

    def _empty_manifest(self) -> Dict[str, Any]:
        return {
            "format_version": CACHE_FORMAT_VERSION,
            "by_digest": {},
            "latest_by_cik": {},
            "latest_by_symbol": {},
            "latest_by_accession": {},
        }

    def _read_manifest(self) -> Dict[str, Any]:
        if not self.manifest_path.exists():
            return self._empty_manifest()
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecFilingEvidenceCacheError(
                "SEC filing cache manifest is unreadable."
            ) from exc
        if not isinstance(payload, dict):
            raise SecFilingEvidenceCacheError("SEC filing cache manifest is invalid.")
        payload.setdefault("by_digest", {})
        payload.setdefault("latest_by_cik", {})
        payload.setdefault("latest_by_symbol", {})
        payload.setdefault("latest_by_accession", {})
        return payload

    def _write_manifest(self, manifest: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            canonical_json_dumps(dict(manifest)) + "\n",
            encoding="utf-8",
        )

    def _object_path(self, digest: str) -> Path:
        return self.objects_dir / f"{digest}.bin"

    def _envelope_path(self, digest: str) -> Path:
        return self.envelopes_dir / f"{digest}.json"

    def get_by_digest(self, digest: str) -> Optional[SecFilingEvidence]:
        normalized = str(digest or "").strip().lower()
        if not normalized:
            return None
        object_path = self._object_path(normalized)
        envelope_path = self._envelope_path(normalized)
        if not object_path.exists() or not envelope_path.exists():
            return None
        try:
            raw = object_path.read_bytes()
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecFilingEvidenceCacheError(
                f"SEC filing object {normalized} is unreadable."
            ) from exc
        evidence = SecFilingEvidence.from_parts(envelope=envelope, raw_bytes=raw)
        verify_filing_digest(evidence)
        if evidence.content_digest != normalized:
            raise SecFilingEvidenceCacheError(
                "SEC filing digest does not match filename."
            )
        return evidence

    def verify_digest(self, digest: str) -> str:
        evidence = self.get_by_digest(digest)
        if evidence is None:
            raise SecFilingEvidenceCacheError(f"SEC filing digest not found: {digest}")
        return verify_filing_digest(evidence)

    def get_latest(
        self,
        *,
        symbol: Optional[str] = None,
        cik: Optional[str] = None,
        accession: Optional[str] = None,
    ) -> Optional[SecFilingEvidence]:
        manifest = self._read_manifest()
        digest = None
        if accession:
            digest = (manifest.get("latest_by_accession") or {}).get(str(accession).strip())
        if digest is None and symbol:
            digest = (manifest.get("latest_by_symbol") or {}).get(
                str(symbol).strip().upper()
            )
        if digest is None and cik:
            digest = (manifest.get("latest_by_cik") or {}).get(pad_cik(cik))
        if not digest:
            return None
        return self.get_by_digest(str(digest))

    def store_if_new(
        self,
        *,
        symbol: str,
        cik: str,
        accession: str,
        form: str,
        filing_date: str,
        primary_document: str,
        raw_bytes: bytes,
        fiscal_year: Optional[int] = None,
        http_status: int = 200,
    ) -> tuple[SecFilingEvidence, bool]:
        evidence = build_filing_evidence(
            symbol=symbol,
            cik=cik,
            accession=accession,
            form=form,
            filing_date=filing_date,
            primary_document=primary_document,
            raw_bytes=raw_bytes,
            fiscal_year=fiscal_year,
            http_status=http_status,
        )
        created = False
        object_path = self._object_path(evidence.content_digest)
        envelope_path = self._envelope_path(evidence.content_digest)
        if object_path.exists():
            stored = self.get_by_digest(evidence.content_digest)
            if stored is None:
                raise SecFilingEvidenceCacheError(
                    "SEC filing digest exists on disk but failed to load."
                )
            evidence = stored
        else:
            self.objects_dir.mkdir(parents=True, exist_ok=True)
            self.envelopes_dir.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(evidence.raw_bytes)
            envelope_path.write_text(
                canonical_json_dumps(evidence.to_envelope()) + "\n",
                encoding="utf-8",
            )
            created = True

        manifest = self._read_manifest()
        by_digest = dict(manifest.get("by_digest") or {})
        meta = dict(by_digest.get(evidence.content_digest) or {})
        symbols = [
            str(item).strip().upper()
            for item in (meta.get("symbols") or [])
            if str(item).strip()
        ]
        if evidence.symbol and evidence.symbol not in symbols:
            symbols.append(evidence.symbol)
        meta.update(
            {
                "cik": evidence.cik,
                "symbols": symbols,
                "accession": evidence.accession,
                "form": evidence.form,
                "filing_date": evidence.filing_date,
                "retrieved_at": meta.get("retrieved_at") or evidence.retrieved_at,
            }
        )
        by_digest[evidence.content_digest] = meta
        latest_by_cik = dict(manifest.get("latest_by_cik") or {})
        latest_by_symbol = dict(manifest.get("latest_by_symbol") or {})
        latest_by_accession = dict(manifest.get("latest_by_accession") or {})
        latest_by_cik[evidence.cik] = evidence.content_digest
        if evidence.symbol:
            latest_by_symbol[evidence.symbol] = evidence.content_digest
        if evidence.accession:
            latest_by_accession[evidence.accession] = evidence.content_digest
        manifest["by_digest"] = by_digest
        manifest["latest_by_cik"] = latest_by_cik
        manifest["latest_by_symbol"] = latest_by_symbol
        manifest["latest_by_accession"] = latest_by_accession
        self._write_manifest(manifest)
        return evidence, created

    def replay_bytes(self, evidence: SecFilingEvidence) -> bytes:
        verify_filing_digest(evidence)
        return evidence.raw_bytes
