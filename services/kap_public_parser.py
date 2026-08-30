"""Extract IFRS/KAP taxonomy rows from a public KAP financial-report page.

Uses taxonomy identifiers (ifrs-full_*, kap-fr_*), not Turkish labels.
Does not normalize, score, or produce Participation verdicts.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from typing import Optional

from services.kap_financial_contract import (
    CONSOLIDATION_CONSOLIDATED,
    CONSOLIDATION_STANDALONE,
    CONSOLIDATION_UNKNOWN,
    NATURE_FLOW,
    NATURE_POINT_IN_TIME,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_UNKNOWN,
    PERIOD_YTD,
    STATEMENT_BALANCE,
    STATEMENT_CASH_FLOW,
    STATEMENT_INCOME,
)
from services.kap_public_contract import (
    LIMITATION_METADATA,
    LIMITATION_STRUCTURE,
    LIMITATION_TAXONOMY,
    SOURCE_PUBLIC_KAP,
    KapPublicFinancialDocument,
    KapPublicTaxonomyRow,
    public_bildirim_url,
)


_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_CONCEPT_TOKEN_RE = re.compile(r"(?i)((?:ifrs-full|kap-fr)_[A-Za-z0-9]+)")
_TAG_RE = re.compile(r"<[^>]+>")

_UNIT_HEADERS = ("Sunum Para Birimi", "Presentation Currency")
_NATURE_HEADERS = ("Finansal Tablo Niteliği", "Nature of Financial Statements")
_PUBLISHED_HEADERS = ("Gönderim Tarihi",)


def _text(raw: object) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", str(raw or ""))).strip()


def _concept(raw: object) -> str:
    text = _text(raw).split("|", 1)[0].strip()
    match = _CONCEPT_TOKEN_RE.search(text)
    return match.group(1) if match else text


def _finite(raw: object) -> Optional[float]:
    text = _text(raw).replace(".", "").replace(" ", "").replace(",", ".")
    if not text or text in {"-", "—"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return value


def _iso_dates(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for day, month, year in _DATE_RE.findall(text):
        found.append(f"{year}-{month}-{day}")
    return tuple(dict.fromkeys(found))


def _period_kind(header: str, dates: tuple[str, ...]) -> str:
    compact = _text(header).upper()
    if "3 AYLIK" in compact or "3-MONTH" in compact:
        return PERIOD_Q
    if len(dates) >= 2:
        start, end = dates[0], dates[1]
        if start[5:] == "01-01" and end[5:] == "12-31":
            return PERIOD_FY
        try:
            start_d = date.fromisoformat(start)
            end_d = date.fromisoformat(end)
        except ValueError:
            return PERIOD_UNKNOWN
        if 80 <= (end_d - start_d).days <= 100:
            return PERIOD_Q
        if start[5:] == "01-01":
            return PERIOD_YTD
        return PERIOD_UNKNOWN
    if len(dates) == 1:
        return PERIOD_FY if dates[0][5:] == "12-31" else PERIOD_YTD
    return PERIOD_UNKNOWN


def _is_current(header: str) -> bool:
    compact = _text(header).casefold()
    if "önceki" in compact or "previous" in compact:
        return False
    return "cari" in compact or "current" in compact


def _is_quarter_header(header: str) -> bool:
    compact = _text(header).upper()
    return "3 AYLIK" in compact or "3-MONTH" in compact


def _nature_for_headers(headers: tuple[str, ...]) -> str:
    for header in headers:
        if len(_iso_dates(header)) >= 2:
            return NATURE_FLOW
    return NATURE_POINT_IN_TIME


def _statement_for(nature: str, concept: str) -> str:
    token = concept.casefold()
    if "cashflow" in token or "statementofcash" in token:
        return STATEMENT_CASH_FLOW
    if nature == NATURE_FLOW:
        return STATEMENT_INCOME
    return STATEMENT_BALANCE


def _cell_after_header(html: str, headers: tuple[str, ...]) -> str:
    for header in headers:
        match = re.search(
            re.escape(header) + r"</td>\s*<td[^>]*>(.*?)</td>",
            html,
            flags=re.I | re.S,
        )
        if match:
            return _text(match.group(1))
    return ""


def _presentation(html: str) -> tuple[str, str, str]:
    unit_raw = _cell_after_header(html, _UNIT_HEADERS)
    nature_raw = _cell_after_header(html, _NATURE_HEADERS)
    unit = unit_raw.upper()
    currency = "TRY" if ("TRY" in unit or unit.endswith("TL") or unit == "TL") else ""
    consolidation = CONSOLIDATION_UNKNOWN
    nature = nature_raw.casefold()
    if "konsolide olmayan" in nature or "unconsolidated" in nature or "standalone" in nature:
        consolidation = CONSOLIDATION_STANDALONE
    elif "konsolide" in nature or "consolidated" in nature:
        consolidation = CONSOLIDATION_CONSOLIDATED
    return currency, unit_raw, consolidation


def _published_at(html: str) -> Optional[str]:
    for header in _PUBLISHED_HEADERS:
        match = re.search(re.escape(header) + r"[:\s]*([0-9.\s:]+)", html, flags=re.I)
        if not match:
            continue
        dates = _iso_dates(match.group(1))
        if dates:
            return dates[0]
    return None


def _year_period_meta(html: str) -> tuple[Optional[str], Optional[str]]:
    year_match = re.search(r"Yıl:\s*(\d{4})", html)
    period_match = re.search(r"Periyot:\s*([0-9A-Za-zÇçĞğİıÖöŞşÜü ]+)", html)
    year = year_match.group(1) if year_match else None
    period = _text(period_match.group(1)) if period_match else None
    return year, period


class _StackedKapHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.concepts: list[str] = []
        self.facts: list[KapPublicTaxonomyRow] = []
        self._stack: list[dict[str, object]] = []
        self._headers: list[str] = []
        self._cell_kind = ""
        self._cell_text: list[str] = []
        self._in_label = False

    def _frame(self) -> Optional[dict[str, object]]:
        return self._stack[-1] if self._stack else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        classes = " ".join(value or "" for key, value in attrs if key == "class")
        if tag == "tr":
            self._stack.append(
                {"headers": [], "concept": "", "label": "", "values": [], "in_label": False}
            )
            self._cell_kind = ""
            self._cell_text = []
            return
        frame = self._frame()
        if frame is None:
            return
        if "taxonomy-field-title" in classes:
            frame["in_label"] = True
        if "context-header" in classes:
            self._cell_kind = "header"
            self._cell_text = []
        elif "taxonomy-field-name" in classes:
            self._cell_kind = "concept"
            self._cell_text = []
        elif "taxonomy-context-value" in classes:
            self._cell_kind = "value"
            self._cell_text = []
        elif frame.get("in_label") and "content-tr" in classes and not frame["label"]:
            self._cell_kind = "label"
            self._cell_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._stack:
            frame = self._stack.pop()
            headers = list(frame["headers"])
            if headers:
                self._headers = headers
            concept = str(frame["concept"] or "")
            values = list(frame["values"])
            if concept:
                self.concepts.append(concept)
            if concept and self._headers:
                nature = _nature_for_headers(tuple(self._headers))
                statement = _statement_for(nature, concept)
                for index, header in enumerate(self._headers):
                    if index >= len(values):
                        break
                    if not _is_current(header):
                        continue
                    value = values[index]
                    if value is None:
                        continue
                    dates = _iso_dates(header)
                    start = dates[0] if len(dates) >= 2 else None
                    end = dates[1] if len(dates) >= 2 else (dates[0] if dates else None)
                    period_kind = _period_kind(header, dates)
                    if period_kind == PERIOD_UNKNOWN:
                        continue
                    self.facts.append(
                        KapPublicTaxonomyRow(
                            concept=concept,
                            raw_label=str(frame["label"] or ""),
                            values=(value,),
                            current_period=True,
                            period_kind=period_kind,
                            period_start=start,
                            period_end=end,
                            fact_nature=nature,
                            statement_type=statement,
                            period_identity="QUARTER" if _is_quarter_header(header) else "CURRENT",
                        )
                    )
            self._cell_kind = ""
            return
        if tag != "td" or not self._cell_kind:
            return
        frame = self._frame()
        if frame is None:
            self._cell_kind = ""
            self._cell_text = []
            return
        payload = _text("".join(self._cell_text))
        if self._cell_kind == "header" and payload:
            frame["headers"].append(payload)  # type: ignore[union-attr]
        elif self._cell_kind == "concept":
            concept = _concept(payload)
            if concept:
                frame["concept"] = concept
        elif self._cell_kind == "value":
            frame["values"].append(_finite(payload))  # type: ignore[union-attr]
        elif self._cell_kind == "label" and payload and not frame["label"]:
            frame["label"] = payload
        self._cell_kind = ""
        self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._cell_kind:
            self._cell_text.append(data)


def parse_public_kap_html(
    html: str,
    *,
    symbol: str,
    disclosure_id: str,
    source_url: str = "",
    cached: bool = False,
) -> KapPublicFinancialDocument:
    """Parse a public KAP Bildirim HTML document into taxonomy rows."""
    if not html or not _text(html):
        raise ValueError(LIMITATION_STRUCTURE)
    currency, unit_label, consolidation = _presentation(html)
    parser = _StackedKapHtmlParser()
    parser.feed(html)
    if not parser.concepts:
        raise ValueError(LIMITATION_TAXONOMY)
    if not currency or not unit_label:
        raise ValueError(LIMITATION_METADATA)
    year, period_label = _year_period_meta(html)
    return KapPublicFinancialDocument(
        symbol=symbol.upper(),
        disclosure_id=str(disclosure_id),
        source_url=source_url or public_bildirim_url(str(disclosure_id)),
        source=SOURCE_PUBLIC_KAP,
        published_at=_published_at(html),
        presentation_currency=currency,
        presentation_unit_label=unit_label,
        consolidation=consolidation,
        report_year=year,
        report_period_label=period_label,
        rows=tuple(parser.facts),
        observed_concepts=tuple(dict.fromkeys(parser.concepts)),
        cached=cached,
        provenance={
            "parser": "kap_public_parser",
            "taxonomy": "ifrs-full/kap-fr",
        },
    )
