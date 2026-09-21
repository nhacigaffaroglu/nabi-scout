import pytest

from services.official_kap_pdr import parse_kap_pdr_text


def test_opk30_alphanumeric_ticker_is_parsed():
    text = """
III-FON PORTFÖY DEĞERİ
Borsa Y.Fonu Türk
OPK30 TL OSMANLI 6.000,00 60,543273 16/04/26 80100103 84,540000 507.240,00 50,87 5,47 5,51
IV-FON TOPLAM DEĞERİ TABLOSU
"""

    parsed = parse_kap_pdr_text(
        text,
        fund_code="TEST",
        report_period="2026-08",
    )

    rows = [
        row
        for row in parsed.holdings
        if row.official_code == "OPK30"
    ]

    assert len(rows) == 1
    assert rows[0].portfolio_weight == pytest.approx(5.51)
    assert rows[0].market_value == pytest.approx(507240.0)


def test_z30kp_alphanumeric_ticker_is_parsed():
    text = """
III-FON PORTFÖY DEĞERİ
Borsa Y.Fonu Türk
Z30KP TL ZİRAAT 30.000,00 271,215303 14/08/26 80100103 287,100000 8.613.000,00 27,92 3,08 3,08
IV-FON TOPLAM DEĞERİ TABLOSU
"""

    parsed = parse_kap_pdr_text(
        text,
        fund_code="TEST",
        report_period="2026-08",
    )

    rows = [
        row
        for row in parsed.holdings
        if row.official_code == "Z30KP"
    ]

    assert len(rows) == 1
    assert rows[0].portfolio_weight == pytest.approx(3.08)
    assert rows[0].market_value == pytest.approx(8613000.0)
