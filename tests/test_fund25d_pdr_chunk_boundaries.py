from __future__ import annotations

import pytest

from services.official_kap_pdr import parse_kap_pdr_text


def _weighted_by_isin(parsed, isin: str):
    return [
        row
        for row in parsed.holdings
        if (row.isin or row.official_code) == isin
        and row.portfolio_weight is not None
    ]


def test_cpu_consecutive_ticker_isin_currency_rows_remain_atomic():
    """
    Official CPU-style KAP text.

    A complete AAPL row is followed by another complete holding whose physical
    row starts TICKER + ISIN + CURRENCY.  The second holding must not be merged
    into the first chunk merely because its first token is the ticker.
    """
    text = """
III-FON PORTFÖY DEĞERİ
HİSSE SENETLERİ
AAPL US0378331005       USD     Apple Inc                        US0378331005                                      8.500,00     246,340631   31/07/26                                                                      317,710800       130.097.250,94        8,36     7,50      7,53
ADI US0326541051        USD      Analog                          US0326541051                                      1.700,00     190,405976   12/05/26                                                                      365,319000        29.918.402,28        1,92     1,72      1,73
                               Devices Inc
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="CPU",
        report_period="2026-08",
    )

    aapl = _weighted_by_isin(parsed, "US0378331005")
    adi = _weighted_by_isin(parsed, "US0326541051")

    assert len(aapl) == 1
    assert aapl[0].portfolio_weight == pytest.approx(7.53)
    assert len(adi) == 1
    assert adi[0].portfolio_weight == pytest.approx(1.73)


def test_cks_trailing_identity_wrap_does_not_swallow_next_isin_row():
    """
    Official CKS-style KAP text.

    A complete lease-certificate row is followed by wrapped issuer/identity
    text and then a new complete ISIN-leading holding.  The trailing identity
    continuation must stay attached to the first row without swallowing the
    next ISIN row.
    """
    text = """
III-FON PORTFÖY DEĞERİ
Özel Sektör Kira Sertifikaları
XS2699906512           USD     ZİRAAT     12/11/26    101                        2,53        2           17.696.000,00    107,329000  30/07/26   4,506329                                                        103,362914      865.995.850,29      16,86    16,14    15,97
                              KATILIM
                               VARLIK                        XS2699906512
                             KİRALAMA
                                A.Ş.
XS3385513471           USD     VAKIF     07/06/28    674                        0,02        2           25.000.000,00    100,015100  02/06/26   5,382763                                                        100,938611    1.194.739.682,50      23,26    22,26    22,03
                              KATILIM                        XS3385513471
                              BANKASI
                                A.Ş.
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="CKS",
        report_period="2026-08",
    )

    first = _weighted_by_isin(parsed, "XS2699906512")
    second = _weighted_by_isin(parsed, "XS3385513471")

    assert len(first) == 1
    assert first[0].portfolio_weight == pytest.approx(15.97)
    assert len(second) == 1
    assert second[0].portfolio_weight == pytest.approx(22.03)




# FUND25D_CASH_DETAIL_OVERLAY_FIXTURES
def _fund25d_cash_detail_only_fixture_text() -> str:
    return """
III-FON PORTFÖY DEĞERİ
Özel Sektör Kira Sertifikaları
Döviz EUR EUR EU EUR 1.121,60 42,986510 31/07/26 54,484100 61.109,37 0,00 0,00 0,00
USD USD FED USD 1.232.514,48 47,293097 31/07/26 47,345200 58.353.644,56 0,00 0,00 1,08
IV-FON TOPLAM DEĞERİ TABLOSU
"""


def _fund25d_cash_detail_plus_overlay_fixture_text() -> str:
    return """
III-FON PORTFÖY DEĞERİ
Özel Sektör Kira Sertifikaları
Döviz EUR EUR EU EUR 1.121,60 42,986510 31/07/26 54,484100 61.109,37 0,00 0,00 0,00
USD USD FED USD 1.232.514,48 47,293097 31/07/26 47,345200 58.353.644,56 0,00 0,00 1,08
IV-FON TOPLAM DEĞERİ TABLOSU
B-) HAZIR DEĞERLER 64.392.063,68 1,19%
C-) ALACAKLAR 0,00 0,00%
E-) BORÇLAR -8.494.799,33 -0,16%
"""


def test_fund25d_currency_cash_detail_is_cash_when_no_aggregate_overlay():
    parsed = parse_kap_pdr_text(
        _fund25d_cash_detail_only_fixture_text(),
        fund_code="CKS",
        report_period="2026-08",
    )

    usd = [
        row
        for row in parsed.holdings
        if (row.official_code or row.security_name_raw) == "USD"
        and row.portfolio_weight is not None
    ]

    assert len(usd) == 1
    assert usd[0].portfolio_weight == pytest.approx(1.08)
    assert usd[0].asset_group == "CASH"


def test_fund25d_hazir_degerler_aggregate_supersedes_currency_components():
    parsed = parse_kap_pdr_text(
        _fund25d_cash_detail_plus_overlay_fixture_text(),
        fund_code="CKS",
        report_period="2026-08",
    )

    overlay = [
        row
        for row in parsed.holdings
        if row.security_name_raw == "HAZIR DEĞERLER"
    ]
    assert len(overlay) == 1
    assert overlay[0].asset_group == "CASH"
    assert overlay[0].portfolio_weight == pytest.approx(1.19)

    assert not any(
        (row.official_code or row.security_name_raw) in {"USD", "EUR"}
        and row.portfolio_weight is not None
        for row in parsed.holdings
    )


def test_fund25d_hazir_degerler_overlay_remains_without_currency_components():
    text = """
III-FON PORTFÖY DEĞERİ
KİRA SERTİFİKALARI
XS2699906512 USD ZİRAAT 12/11/26 101 2,53 2 17.696.000,00 107,329000 30/07/26 4,506329 103,362914 865.995.850,29 16,86 16,14 15,97
IV-FON TOPLAM DEĞERİ TABLOSU
B-) HAZIR DEĞERLER 64.392.063,68 1,19%
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="CKS",
        report_period="2026-08",
    )

    overlay = [
        row
        for row in parsed.holdings
        if row.security_name_raw == "HAZIR DEĞERLER"
    ]
    assert len(overlay) == 1
    assert overlay[0].asset_group == "CASH"
    assert overlay[0].portfolio_weight == pytest.approx(1.19)
