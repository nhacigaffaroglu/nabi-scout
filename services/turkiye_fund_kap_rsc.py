"""Parse official KAP Next.js RSC payloads for fund identity and documents.

Uses the public ozet/genel/Bildirim RSC representations. No undocumented
private APIs. File identity is the official fileOid / disclosureIndex.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from services.official_kap_fund import (
    OZET_LABEL_FOUNDER,
    OZET_LABEL_UMBRELLA_NAME,
    OZET_LABEL_UMBRELLA_TYPE,
)
from services.official_tefas import normalize_fund_code

_GENERAL_INFO = re.compile(
    r'"generalInfo":\{"objId":"(?P<objId>[^"]+)","fundType":"(?P<fundType>[^"]*)",'
    r'"fundName":"(?P<fundName>[^"]*)","mkkMemberOid":"(?P<mkkMemberOid>[^"]*)",'
    r'"title":"(?P<title>[^"]*)","fundCode":"(?P<fundCode>[^"]*)"'
)
_FILE_DOC = re.compile(
    r'"(?P<kind>IZAHNAME|ICTUZUK|BILGI_FORMU|TANITIM_FORMU|IHRAC_BELGESI)"'
    r':\[\{"fileOid":"(?P<fileOid>[^"]+)","disclosureIndex":(?P<disclosureIndex>\d+),'
    r'"fileName":"(?P<fileName>[^"]*)"'
)
_ATTACHMENT = re.compile(
    r'\{"objId":"(?P<objId>[0-9a-f]+)","fileName":"(?P<fileName>[^"]+)","fileExtension":"(?P<ext>[^"]*)"\}'
)
_ITEM = re.compile(
    r'"itemName":"(?P<itemName>[^"]*)","itemKey":"(?P<itemKey>[^"]*)","value":"(?P<value>[^"]*)"'
)
_OZET_VALUE = re.compile(
    r'"children":"(?P<label>Kurucunun Ünvanı|Fonun Süresi|'
    r'Fonun Bağlı Olduğu Şemsiye Fonun Ünvanı|Fonun Bağlı Olduğu Şemsiye Fonun Türü)"'
    r'.{0,800}?"children":"(?P<value>[^"]{2,160})"',
    flags=re.S,
)

DOC_KIND_YBF = "BILGI_FORMU"
DOC_KIND_IZAHNAME = "IZAHNAME"
DOC_KIND_ICTUZUK = "ICTUZUK"


def parse_kap_ozet_rsc(text: str) -> dict[str, Any]:
    body = str(text or "")
    info_match = _GENERAL_INFO.search(body)
    info = info_match.groupdict() if info_match else {}
    documents: dict[str, dict[str, Any]] = {}
    for match in _FILE_DOC.finditer(body):
        row = match.groupdict()
        documents[row["kind"]] = {
            "file_oid": row["fileOid"],
            "disclosure_index": int(row["disclosureIndex"]),
            "file_name": row["fileName"],
            "kind": row["kind"],
        }
    ozet_fields: dict[str, str] = {}
    for match in _OZET_VALUE.finditer(body):
        label = str(match.group("label") or "").strip()
        value = str(match.group("value") or "").strip()
        if label and value and value != label and label not in ozet_fields:
            ozet_fields[label] = value
    if info.get("title") and OZET_LABEL_FOUNDER not in ozet_fields:
        ozet_fields[OZET_LABEL_FOUNDER] = info["title"]
    if info.get("fundName") and OZET_LABEL_UMBRELLA_NAME not in ozet_fields:
        # name is the fund, not the umbrella; do not guess
        pass
    return {
        "fund_code": normalize_fund_code(info.get("fundCode")),
        "official_name": info.get("fundName") or None,
        "founder": info.get("title") or ozet_fields.get(OZET_LABEL_FOUNDER),
        "fund_type": info.get("fundType") or None,
        "mkk_member_oid": info.get("mkkMemberOid") or None,
        "kap_obj_id": info.get("objId") or None,
        "documents": documents,
        "ozet_fields": ozet_fields,
        "ybf_file_oid": (documents.get(DOC_KIND_YBF) or {}).get("file_oid"),
        "izahname_file_oid": (documents.get(DOC_KIND_IZAHNAME) or {}).get("file_oid"),
        "ictuzuk_file_oid": (documents.get(DOC_KIND_ICTUZUK) or {}).get("file_oid"),
        "resolved": bool(info.get("fundCode") and documents),
    }


def parse_kap_genel_rsc(text: str) -> dict[str, Any]:
    items: dict[str, str] = {}
    labels: dict[str, str] = {}
    for match in _ITEM.finditer(str(text or "")):
        key = str(match.group("itemKey") or "").strip()
        value = str(match.group("value") or "").strip()
        name = str(match.group("itemName") or "").strip()
        if key and value and key not in items:
            items[key] = value
            labels[key] = name
    isin = items.get("kpy81_acc1_ISIN") or None
    return {
        "items": items,
        "labels": labels,
        "isin": isin,
        "resolved": bool(items),
    }


def parse_kap_bildirim_rsc(text: str) -> dict[str, Any]:
    attachments = [
        {
            "file_oid": match.group("objId"),
            "file_name": match.group("fileName"),
            "extension": match.group("ext"),
        }
        for match in _ATTACHMENT.finditer(str(text or ""))
    ]
    pdfs = [row for row in attachments if str(row.get("extension") or "").lower() == "pdf"]
    chosen = pdfs[0] if pdfs else (attachments[0] if attachments else None)
    return {
        "attachments": attachments,
        "file_oid": (chosen or {}).get("file_oid"),
        "file_name": (chosen or {}).get("file_name"),
        "resolved": bool(chosen and chosen.get("file_oid")),
    }


def kap_file_url(file_oid: Optional[str]) -> str:
    oid = str(file_oid or "").strip()
    if not oid:
        return ""
    return f"https://www.kap.org.tr/tr/api/file/download/{oid}"
