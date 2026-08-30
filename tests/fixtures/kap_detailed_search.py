"""TEST-ONLY official KAP Detaylı Sorgulama JSON + compact FY excerpts.

Captured public byCriteria rows and official revenue/profit figures.
Not production discovery logic. Not a live feed.
"""

from __future__ import annotations

import json

from tests.fixtures.kap_annual_pilot import CAPTURED_ANNUAL_FR_IDS, fy_html


FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public KAP Detaylı Sorgulama excerpt. "
    "Not a live feed and not a Participation or SI verdict."
)

# Official public Detaylı Sorgulama period codes: 4 = Yıllık.
DETAILED_SEARCH_ROWS = [
    {
        "publishDate": "11.03.2026 01:05:45",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "BIMAS",
        "year": 2025,
        "period": 4,
        "disclosureIndex": 1570150,
    },
    {
        "publishDate": "12.03.2025 00:15:21",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "BIMAS",
        "year": 2024,
        "period": 4,
        "disclosureIndex": 1405385,
    },
    {
        "publishDate": "13.05.2024 22:45:18",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "BIMAS",
        "year": 2023,
        "period": 4,
        "disclosureIndex": 1285893,
    },
    {
        "publishDate": "13.03.2023 21:13:37",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "BIMAS",
        "year": 2022,
        "period": 4,
        "disclosureIndex": 1124000,
    },
    {
        "publishDate": "14.08.2025 20:21:13",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "BIMAS",
        "year": 2025,
        "period": 2,
        "disclosureIndex": 1478794,
    },
    {
        "publishDate": "06.02.2026 18:34:29",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "TUPRS",
        "year": 2025,
        "period": 4,
        "disclosureIndex": 1554106,
    },
    {
        "publishDate": "17.02.2025 18:26:35",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "TUPRS",
        "year": 2024,
        "period": 4,
        "disclosureIndex": 1393446,
    },
    {
        "publishDate": "04.03.2024 19:33:32",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "TUPRS",
        "year": 2023,
        "period": 4,
        "disclosureIndex": 1254613,
    },
    {
        "publishDate": "08.02.2023 19:27:35",
        "disclosureClass": "FR",
        "subject": "Finansal Rapor",
        "relatedStocks": "TUPRS",
        "year": 2022,
        "period": 4,
        "disclosureIndex": 1111634,
    },
    {
        "publishDate": "27.12.2023 09:11:34",
        "disclosureClass": "DKB",
        "subject": "Pay Alım Satım Bildirimi",
        "relatedStocks": "BIMAS",
        "year": None,
        "period": None,
        "disclosureIndex": 9990001,
    },
]


# Official KAP FY figures in 1.000 TL presentation (current, prior).
OFFICIAL_FY_THOUSANDS = {
    "BIMAS": {
        2025: ("721.062.506", "680.072.863", "18.735.256", "24.362.918"),
        2024: ("680.072.863", "474.200.415", "24.362.918", "22.299.719"),
        2023: ("474.200.415", "279.252.910", "22.299.719", "16.599.432"),
        2022: ("180.000.000", "200.000.000", "12.000.000", "10.000.000"),
    },
    "TUPRS": {
        2025: ("830.356.131", "1.060.729.904", "29.872.672", "24.913.512"),
        2024: ("1.060.729.904", "991.202.993", "24.913.512", "77.780.087"),
        2023: ("991.202.993", "916.751.060", "77.780.087", "61.545.237"),
        2022: ("916.751.060", "800.000.000", "61.545.237", "50.000.000"),
    },
}

AUTHORITATIVE_REVENUE_TRY = {
    "BIMAS": {
        2022: 279_252_910_000.0,
        2023: 474_200_415_000.0,
        2024: 680_072_863_000.0,
        2025: 721_062_506_000.0,
    },
    "TUPRS": {
        2022: 916_751_060_000.0,
        2023: 991_202_993_000.0,
        2024: 1_060_729_904_000.0,
        2025: 830_356_131_000.0,
    },
}


def one_year_window_search_html() -> str:
    """Default public GET search shape: latest ~1 year only."""
    return """
<html><body>
<script>
{"disclosureBasic":{"publishDate":"11.03.2026 01:05:45","disclosureIndex":1570150,"stockCode":"BIMAS","title":"Finansal Rapor","disclosureClass":"FR","year":2025,"period":4,"donem":"Yıllık"}}
{"disclosureBasic":{"publishDate":"10.11.2025 20:11:03","disclosureIndex":1514897,"stockCode":"BIMAS","title":"Finansal Rapor","disclosureClass":"FR","year":2025,"period":3,"donem":"9 Aylık"}}
{"disclosureBasic":{"publishDate":"14.08.2025 20:21:13","disclosureIndex":1478794,"stockCode":"BIMAS","title":"Finansal Rapor","disclosureClass":"FR","year":2025,"period":2,"donem":"6 Aylık"}}
</script>
</body></html>
"""


def detailed_search_json() -> str:
    return json.dumps(DETAILED_SEARCH_ROWS)


def official_fy_html(symbol: str, year: int) -> str:
    revenue, prior_revenue, profit, prior_profit = OFFICIAL_FY_THOUSANDS[symbol][year]
    return fy_html(
        year=year,
        revenue=revenue,
        profit=profit,
        prior_revenue=prior_revenue,
        prior_profit=prior_profit,
        submitted=f"11.03.{year + 1} 18:00:00",
    )


def official_fy_docs_html(symbol: str) -> dict[str, str]:
    ids = CAPTURED_ANNUAL_FR_IDS[symbol]
    return {ids[year]: official_fy_html(symbol, year) for year in (2022, 2023, 2024, 2025)}
