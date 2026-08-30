"""TEST-ONLY captured KAP annual-history fixtures. Not live issuer authority."""

from __future__ import annotations

from tests.fixtures.kap_public_pilot import compact_public_html

FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public KAP annual FR excerpt for parser regression. "
    "Not a live feed and not a Participation or SI verdict."
)

# Captured public notification IDs for tests only. Not production discovery logic.
CAPTURED_ANNUAL_FR_IDS = {
    "ASELS": {
        2025: "1561039",
        2024: "1395801",
        2023: "1262825",
    },
    "BIMAS": {2025: "1570150"},
    "TUPRS": {2025: "1554106"},
}


def fr_search_html() -> str:
    """Official KAP search shape: disclosureBasic JSON plus checkbox rows."""
    return """
<html><body>
<script>
{"disclosureBasic":{"publishDate":"04.08.2026 18:39:41","disclosureIndex":1643141,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2026,"period":2,"donem":"6 Aylık"}}
{"disclosureBasic":{"publishDate":"28.04.2026 18:00:00","disclosureIndex":1598316,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2026,"period":1,"donem":"3 Aylık"}}
{"disclosureBasic":{"publishDate":"24.02.2026 18:27:36","disclosureIndex":1561039,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2025,"period":4,"donem":"Yıllık"}}
{"disclosureBasic":{"publishDate":"24.02.2026 18:27:13","disclosureIndex":1561038,"stockCode":"ASELS","title":"Faaliyet Raporu (Konsolide)","disclosureClass":"FR","year":2025,"period":4,"donem":"Yıllık"}}
{"disclosureBasic":{"publishDate":"25.02.2025 18:10:00","disclosureIndex":1395801,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2024,"period":4,"donem":"Yıllık"}}
{"disclosureBasic":{"publishDate":"26.02.2024 18:00:00","disclosureIndex":1262825,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2023,"period":4,"donem":"Yıllık"}}
{"disclosureBasic":{"publishDate":"27.02.2023 18:00:00","disclosureIndex":1117839,"stockCode":"ASELS","title":"Finansal Rapor","disclosureClass":"FR","year":2022,"period":4,"donem":"Yıllık"}}
</script>
<table>
<tr><td><input id="1561039" type="checkbox"></td><td>ASELS</td><td>Finansal Rapor</td><td>FR</td><td>24.02.2026</td><td>2025</td><td>Yıllık</td></tr>
</table>
</body></html>
"""


def checkbox_only_search_html() -> str:
    return """
<table>
<tr><td><input id="2001" type="checkbox"></td><td>PILOT</td><td>Finansal Rapor</td><td>FR</td><td>11.03.2026</td><td>2025</td><td>Yıllık</td></tr>
<tr><td><input id="2002" type="checkbox"></td><td>PILOT</td><td>Finansal Rapor</td><td>FR</td><td>10.11.2025</td><td>2025</td><td>9 Aylık</td></tr>
</table>
"""


def fy_html(
    *,
    year: int,
    revenue: str,
    profit: str,
    assets: str = "500.000.000",
    equity: str = "200.000.000",
    cash: str = "40.000.000",
    operating: str = "20.000.000",
    current_assets: str = "250.000.000",
    current_liabilities: str = "100.000.000",
    prior_revenue: str = "90.000.000",
    prior_profit: str = "9.000.000",
    consolidation: str = "Konsolide",
    unit: str = "1.000 TL",
    submitted: str = "",
    include_gross: bool = False,
) -> str:
    prior_year = year - 1
    submitted_at = submitted or f"24.02.{year + 1} 18:00:00"
    extra_is = ""
    extra_bs_header_ok = compact_public_html(
        unit=unit,
        consolidation=consolidation,
        bs_current=f"Cari Dönem<br>31.12.{year}",
        bs_prior=f"Önceki Dönem<br>31.12.{prior_year}",
        is_current=f"Cari Dönem 01.01.{year} - 31.12.{year}",
        is_prior=f"Önceki Dönem 01.01.{prior_year} - 31.12.{prior_year}",
        include_quarter=False,
        include_unknown=False,
        cash=cash,
        assets=assets,
        equity=equity,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        revenue=revenue,
        operating=operating,
        profit=profit,
    )
    html = extra_bs_header_ok.replace(
        "Gönderim Tarihi:04.08.2026 18:39:41",
        f"Gönderim Tarihi:{submitted_at}",
    ).replace("Yıl:2026", f"Yıl:{year}").replace("Periyot:2", "Periyot:Yıllık").replace(
        "70.956.004", prior_revenue
    ).replace(
        "9.000.000", prior_profit
    )
    if include_gross:
        html = html.replace(
            'ifrs-full_Revenue',
            'ifrs-full_GrossProfit',
            1,
        )
        # restore revenue row; prepend gross as its own row via a simple insert
        html = html.replace(
            '<div class="gwt-Label taxonomy-field-name">ifrs-full_GrossProfit|</div>',
            '<div class="gwt-Label taxonomy-field-name">ifrs-full_Revenue|</div>',
            1,
        )
        html = html.replace(
            "</table>\n</html>",
            (
                '<tr class="data-input-row">'
                '<td class="taxonomy-field-name-cell">'
                '<div class="gwt-Label taxonomy-field-name">ifrs-full_GrossProfit|</div></td>'
                '<td class="taxonomy-field-title">'
                '<div class="gwt-Label multi-language-content content-tr">Brüt Kar</div></td>'
                '<td class="taxonomy-context-value">30.000.000</td>'
                '<td class="taxonomy-context-value">25.000.000</td></tr>'
                "</table>\n</html>"
            ),
        )
    return html


def annual_series_html() -> dict[int, str]:
    """Comparable consolidated FY history used for YoY / 3Y CAGR tests."""
    return {
        2022: fy_html(year=2022, revenue="100.000.000", profit="10.000.000", prior_revenue="80.000.000"),
        2023: fy_html(year=2023, revenue="110.000.000", profit="12.000.000", prior_revenue="100.000.000"),
        2024: fy_html(year=2024, revenue="121.000.000", profit="14.000.000", prior_revenue="110.000.000"),
        2025: fy_html(year=2025, revenue="133.100.000", profit="16.000.000", prior_revenue="121.000.000"),
    }


def restated_prior_html() -> str:
    """2025 filing restates 2024 revenue via the prior-period column."""
    return fy_html(
        year=2025,
        revenue="133.100.000",
        profit="16.000.000",
        prior_revenue="125.000.000",
        submitted="24.02.2026 18:27:36",
    )


def standalone_2022_html() -> str:
    return fy_html(
        year=2022,
        revenue="90.000.000",
        profit="8.000.000",
        consolidation="Konsolide Olmayan",
    )
