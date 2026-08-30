"""TEST-ONLY synthetic KAP REST payloads. Not official KAP production data."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from tests.fixtures.kap_financial_pilot import asels_raw_lines, bimas_raw_lines, tuprs_raw_lines

FIXTURE_DISCLAIMER = (
    "TEST-ONLY synthetic KAP REST payloads. Not official KAP production data."
)


class MemoryKapTransport:
    def __init__(self, payloads: Mapping[str, Any], *, fail: bool = False) -> None:
        self.payloads = dict(payloads)
        self.fail = fail
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def request(self, service: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append((service, dict(params)))
        if self.fail:
            raise RuntimeError("synthetic transport failure")
        payload = self.payloads.get(service)
        if callable(payload):
            payload = payload(params)
        if not isinstance(payload, Mapping):
            return {}
        return payload


def _line_dicts(symbol: str) -> list[dict[str, Any]]:
    builders = {"ASELS": asels_raw_lines, "BIMAS": bimas_raw_lines, "TUPRS": tuprs_raw_lines}
    return [line.to_dict() for line in builders[symbol]()]


def financial_detail(symbol: str, *, disclosure_id: str, attachment_ref: Optional[str] = None) -> dict[str, Any]:
    return {
        "disclosure_id": disclosure_id,
        "symbol": symbol,
        "member_code": f"TEST-{symbol}",
        "published_at": "2025-02-15",
        "title": f"{symbol} fixture disclosure",
        "attachment_ref": attachment_ref,
        "explicit_financial_report_candidate": True,
        "structured_raw_lines": _line_dicts(symbol),
        "disclaimer": FIXTURE_DISCLAIMER,
    }


def unknown_detail(symbol: str, *, disclosure_id: str) -> dict[str, Any]:
    return {
        "disclosure_id": disclosure_id,
        "symbol": symbol,
        "title": f"{symbol} finansal rapor",
        "explicit_financial_report_candidate": None,
        "disclaimer": FIXTURE_DISCLAIMER,
    }


def missing_attachment_detail(symbol: str, *, disclosure_id: str) -> dict[str, Any]:
    return {
        "disclosure_id": disclosure_id,
        "symbol": symbol,
        "explicit_financial_report_candidate": True,
        "attachment_ref": "missing-ref",
        "structured_raw_lines": [],
        "disclaimer": FIXTURE_DISCLAIMER,
    }


def list_payload(*summaries: dict[str, Any]) -> dict[str, Any]:
    return {"disclosures": list(summaries), "disclaimer": FIXTURE_DISCLAIMER}


def attachment_payload(ref: str, *, available: bool = True) -> dict[str, Any]:
    return {
        "attachment_ref": ref,
        "available": available,
        "content_type": "application/pdf" if available else None,
        "payload": b"%PDF-FIXTURE" if available else None,
        "disclaimer": FIXTURE_DISCLAIMER,
    }


def pilot_transport() -> MemoryKapTransport:
    details = {
        "ASELS-FIN": financial_detail("ASELS", disclosure_id="ASELS-FIN"),
        "BIMAS-FIN": financial_detail("BIMAS", disclosure_id="BIMAS-FIN"),
        "TUPRS-UNK": unknown_detail("TUPRS", disclosure_id="TUPRS-UNK"),
        "ASELS-MISS": missing_attachment_detail("ASELS", disclosure_id="ASELS-MISS"),
    }
    attachments = {
        "ASELS-ATT": attachment_payload("ASELS-ATT"),
        "missing-ref": attachment_payload("missing-ref", available=False),
    }

    def _detail(params: Mapping[str, Any]) -> dict[str, Any]:
        return details.get(str(params.get("disclosure_id") or ""), {})

    def _list(params: Mapping[str, Any]) -> dict[str, Any]:
        symbol = str(params.get("symbol") or "")
        rows = {
            "ASELS": [
                {"disclosure_id": "ASELS-FIN", "symbol": "ASELS", "title": "fixture"},
                {"disclosure_id": "ASELS-MISS", "symbol": "ASELS", "title": "fixture missing"},
            ],
            "BIMAS": [{"disclosure_id": "BIMAS-FIN", "symbol": "BIMAS", "title": "fixture"}],
            "TUPRS": [{"disclosure_id": "TUPRS-UNK", "symbol": "TUPRS", "title": "fixture unknown"}],
        }
        return list_payload(*rows.get(symbol, []))

    def _attachment(params: Mapping[str, Any]) -> dict[str, Any]:
        return attachments.get(str(params.get("attachment_ref") or ""), attachment_payload("", available=False))

    return MemoryKapTransport(
        {
            "disclosures": _list,
            "disclosureDetail": _detail,
            "downloadAttachment": _attachment,
        }
    )
