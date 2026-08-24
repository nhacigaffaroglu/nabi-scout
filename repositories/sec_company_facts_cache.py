from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.sec_company_facts_evidence import (
    CACHE_FORMAT_VERSION,
    SecCompanyFactsCacheError,
    SecCompanyFactsEvidence,
    build_company_facts_evidence,
    canonical_json_dumps,
    digest_company_facts_payload,
    pad_cik,
    verify_evidence_digest,
)
from services.sec_financial_client import SECFinancialClient

DEFAULT_CACHE_ROOT = Path("data/private/sec_company_facts")
OBJECTS_DIRNAME = "objects"
MANIFEST_FILENAME = "manifest.json"


def default_sec_company_facts_cache_root() -> Path:
    return DEFAULT_CACHE_ROOT


class SecCompanyFactsCache:
    """Append-only, content-addressed SEC Company Facts evidence cache.

    Does not call providers. Replay uses only stored raw payloads.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else default_sec_company_facts_cache_root()
        self.objects_dir = self.root / OBJECTS_DIRNAME
        self.manifest_path = self.root / MANIFEST_FILENAME

    def _empty_manifest(self) -> Dict[str, Any]:
        return {
            "format_version": CACHE_FORMAT_VERSION,
            "by_digest": {},
            "latest_by_cik": {},
            "latest_by_symbol": {},
        }

    def _read_manifest(self) -> Dict[str, Any]:
        if not self.manifest_path.exists():
            return self._empty_manifest()
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecCompanyFactsCacheError(
                "SEC Company Facts cache manifest is unreadable."
            ) from exc
        if not isinstance(payload, dict):
            raise SecCompanyFactsCacheError(
                "SEC Company Facts cache manifest is invalid."
            )
        payload.setdefault("by_digest", {})
        payload.setdefault("latest_by_cik", {})
        payload.setdefault("latest_by_symbol", {})
        return payload

    def _write_manifest(self, manifest: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        text = canonical_json_dumps(dict(manifest)) + "\n"
        self.manifest_path.write_text(text, encoding="utf-8")

    def _object_path(self, digest: str) -> Path:
        return self.objects_dir / f"{digest}.json"

    def get_by_digest(self, digest: str) -> Optional[SecCompanyFactsEvidence]:
        normalized = str(digest or "").strip().lower()
        if not normalized:
            return None
        path = self._object_path(normalized)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecCompanyFactsCacheError(
                f"SEC Company Facts object {normalized} is unreadable."
            ) from exc
        evidence = SecCompanyFactsEvidence.from_dict(payload)
        verify_evidence_digest(evidence)
        if evidence.content_digest != normalized:
            raise SecCompanyFactsCacheError(
                "SEC Company Facts object digest does not match filename."
            )
        return evidence

    def verify_digest(self, digest: str) -> str:
        evidence = self.get_by_digest(digest)
        if evidence is None:
            raise SecCompanyFactsCacheError(
                f"SEC Company Facts digest not found: {digest}"
            )
        return verify_evidence_digest(evidence)

    def get_latest(
        self,
        *,
        symbol: Optional[str] = None,
        cik: Optional[str] = None,
    ) -> Optional[SecCompanyFactsEvidence]:
        manifest = self._read_manifest()
        digest = None
        if symbol:
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
        raw_payload: Dict[str, Any],
        http_status: int = 200,
    ) -> tuple[SecCompanyFactsEvidence, bool]:
        requested_symbol = str(symbol or "").strip().upper()
        evidence = build_company_facts_evidence(
            symbol=requested_symbol,
            cik=cik,
            raw_payload=raw_payload,
            http_status=http_status,
        )
        created = False
        object_path = self._object_path(evidence.content_digest)
        if object_path.exists():
            stored = self.get_by_digest(evidence.content_digest)
            if stored is None:
                raise SecCompanyFactsCacheError(
                    "SEC Company Facts digest exists on disk but failed to load."
                )
            evidence = stored
        else:
            self.objects_dir.mkdir(parents=True, exist_ok=True)
            object_path.write_text(
                canonical_json_dumps(evidence.to_dict()) + "\n",
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
        if requested_symbol and requested_symbol not in symbols:
            symbols.append(requested_symbol)
        meta.update(
            {
                "cik": evidence.cik,
                "symbols": symbols,
                "retrieved_at": meta.get("retrieved_at") or evidence.retrieved_at,
            }
        )
        by_digest[evidence.content_digest] = meta
        latest_by_cik = dict(manifest.get("latest_by_cik") or {})
        latest_by_symbol = dict(manifest.get("latest_by_symbol") or {})
        latest_by_cik[evidence.cik] = evidence.content_digest
        if requested_symbol:
            latest_by_symbol[requested_symbol] = evidence.content_digest
        manifest["by_digest"] = by_digest
        manifest["latest_by_cik"] = latest_by_cik
        manifest["latest_by_symbol"] = latest_by_symbol
        self._write_manifest(manifest)
        return evidence, created

    def replay(self, evidence: SecCompanyFactsEvidence) -> Dict[str, Any]:
        verify_evidence_digest(evidence)
        client = SECFinancialClient(contact_email="cache-replay@localhost")
        return client.extract_financials(evidence.raw_payload)

    def has_digest(self, digest: str) -> bool:
        return self._object_path(str(digest or "").strip().lower()).exists()


def digest_payload(payload: Dict[str, Any]) -> str:
    return digest_company_facts_payload(payload)
