"""Captured public KAP HTML excerpts. Not live issuer authority after capture."""

from __future__ import annotations

# One-time public retrieval IDs. Latest FR pages as of 2026-08-30.
PILOT_PUBLIC_REPORTS = {
    "ASELS": "1643141",
    "BIMAS": "1651656",
    "TUPRS": "1643116",
}

FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public KAP Bildirim HTML excerpt for parser regression. "
    "Not a live feed and not a Participation verdict."
)


def _row(concept: str, label: str, *values: str) -> str:
    value_cells = "".join(
        f'<td class="taxonomy-context-value">{item}</td>' for item in values
    )
    return (
        f'<tr class="data-input-row">'
        f'<td class="taxonomy-field-name-cell">'
        f'<div class="gwt-Label taxonomy-field-name">{concept}|</div></td>'
        f'<td class="taxonomy-field-title">'
        f'<div class="gwt-Label multi-language-content content-tr">{label}</div></td>'
        f"{value_cells}</tr>"
    )


def compact_public_html(
    *,
    unit: str = "1.000 TL",
    consolidation: str = "Konsolide",
    bs_current: str = "Cari Dönem<br>30.06.2026",
    bs_prior: str = "Önceki Dönem<br>31.12.2025",
    is_current: str = "Cari Dönem 01.01.2026 - 30.06.2026",
    is_prior: str = "Önceki Dönem 01.01.2025 - 30.06.2025",
    q_current: str = "Cari Dönem 3 Aylık 01.04.2026 - 30.06.2026",
    q_prior: str = "Önceki Dönem 3 Aylık 01.04.2025 - 30.06.2025",
    include_unknown: bool = True,
    include_quarter: bool = True,
    cash: str = "39.468.926",
    assets: str = "549.748.035",
    equity: str = "200.000.000",
    current_assets: str = "248.765.565",
    current_liabilities: str = "100.000.000",
    revenue: str = "88.494.252",
    operating: str = "10.000.000",
    profit: str = "14.439.306",
    unknown_value: str = "1.000",
) -> str:
    unknown_row = (
        _row("ifrs-full_Inventories", "Stoklar", unknown_value, "900")
        if include_unknown
        else ""
    )
    quarter_headers = (
        f'<td class="context-header">{q_current}</td>'
        f'<td class="context-header">{q_prior}</td>'
        if include_quarter
        else ""
    )
    quarter_values = ("51.782.243", "39.038.714") if include_quarter else ()
    return f"""
<html>
  <div>Gönderim Tarihi:04.08.2026 18:39:41</div>
  <div>Bildirim Tipi:FR</div>
  <div>Yıl:2026</div>
  <div>Periyot:2</div>
  <table class="financial-header-table">
    <tr><td>Sunum Para Birimi</td><td>{unit}</td></tr>
    <tr><td>Finansal Tablo Niteliği</td><td>{consolidation}</td></tr>
  </table>
  <table class="financial-table">
    <tr>
      <td class="context-header">{bs_current}</td>
      <td class="context-header">{bs_prior}</td>
    </tr>
    {_row("ifrs-full_CashAndCashEquivalents", "Nakit ve Nakit Benzerleri", cash, "34.251.653")}
    {_row("ifrs-full_CurrentAssets", "TOPLAM DÖNEN VARLIKLAR", current_assets, "206.057.730")}
    {_row("ifrs-full_Assets", "TOPLAM VARLIKLAR", assets, "508.228.606")}
    {_row("ifrs-full_CurrentLiabilities", "TOPLAM KISA VADELİ YÜKÜMLÜLÜKLER", current_liabilities, "90.000.000")}
    {_row("ifrs-full_Equity", "TOPLAM ÖZKAYNAKLAR", equity, "180.000.000")}
    {unknown_row}
  </table>
  <table class="financial-table">
    <tr>
      <td class="context-header">{is_current}</td>
      <td class="context-header">{is_prior}</td>
      {quarter_headers}
    </tr>
    {_row("ifrs-full_Revenue", "Hasılat", revenue, "70.956.004", *quarter_values)}
    {_row("ifrs-full_ProfitLossFromOperatingActivities", "Esas Faaliyet Kârı", operating, "8.000.000", *(("5.000.000", "4.000.000") if include_quarter else ()))}
    {_row("ifrs-full_ProfitLoss", "Dönem Karı", profit, "9.000.000", *(("6.000.000", "5.000.000") if include_quarter else ()))}
  </table>
</html>
"""


def asels_public_html() -> str:
    return compact_public_html()


def fy_public_html() -> str:
    return compact_public_html(
        bs_current="Cari Dönem<br>31.12.2025",
        bs_prior="Önceki Dönem<br>31.12.2024",
        is_current="Cari Dönem 01.01.2025 - 31.12.2025",
        is_prior="Önceki Dönem 01.01.2024 - 31.12.2024",
        include_quarter=False,
        cash="34.251.653",
        assets="508.228.606",
        revenue="120.000.000",
        profit="12.000.000",
    )


def missing_unit_html() -> str:
    return compact_public_html(unit="")


def unknown_only_html() -> str:
    return compact_public_html(include_unknown=True)
