from services.official_kap_pdr import _parse_ticker_row


def parse_row(text, section="FUND"):
    return _parse_ticker_row(
        text,
        fund_code="TEST",
        report_period=None,
        report_date=None,
        section=section,
        fund_total_value=None,
        source_notification_id=None,
        source_attachment=None,
    )


def test_rr9_is_not_parsed_as_pie():
    row = parse_row(
        "RR9 - RE-PIE TL RE-PIE "
        "850,00 1.000,000000 16/03/22 "
        "4.491,685472 3.817.932,65 "
        "100,00 0,25 0,24",
        section="REPO",
    )

    assert row is not None
    assert row.isin is None
    assert row.official_code == "RR9"
    assert row.portfolio_weight == 0.24
    assert row.market_value == 3817932.65


def test_gldtr_is_not_parsed_as_qnb():
    row = parse_row(
        "GLDTR - QNB TL QNB "
        "8.910,00 534,457118 31/08/26 "
        "80100103 572,000000 5.096.520,00 "
        "10,70 4,30 4,67"
    )

    assert row is not None
    assert row.isin is None
    assert row.official_code == "GLDTR"
    assert row.portfolio_weight == 4.67
    assert row.market_value == 5096520.0


def test_existing_isin_is_never_replaced():
    row = parse_row(
        "KHC - PARDUS TL PARDUS "
        "TRYA1PY00073 "
        "1.000.000,00 1,624011 09/01/26 "
        "2,264562 2.264.562,00 "
        "50,45 6,67 6,69",
        section="REPO",
    )

    assert row is not None
    assert row.isin == "TRYA1PY00073"
    assert row.official_code == "TRYA1PY00073"
    assert row.portfolio_weight == 6.69
