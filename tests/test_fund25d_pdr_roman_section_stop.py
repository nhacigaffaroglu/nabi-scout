from services.official_kap_pdr import _cut_holdings_body


def test_cut_holdings_before_roman_vii_portfolio_transactions():
    text = """
III-FON PORTFÖY DEĞERİ
KİRA SERTİFİKALARI
SAFE HOLDING ROW
VII-PORTFÖYE SATIŞLAR
TRD111111F11 HAZINE 1,000 1.000.000,00
"""
    result = _cut_holdings_body(text)
    assert "SAFE HOLDING ROW" in result
    assert "VII-PORTFÖYE SATIŞLAR" not in result
    assert "TRD111111F11" not in result


def test_cut_holdings_before_roman_viii_itfalar():
    text = """
III-FON PORTFÖY DEĞERİ
KİRA SERTİFİKALARI
SAFE HOLDING ROW
VIII-İTFALAR
TRD210826F19 HAZINE 21/08/26 21/08/26 1,007 1.000.000,00 1.000.000,00
"""
    result = _cut_holdings_body(text)
    assert "SAFE HOLDING ROW" in result
    assert "VIII-İTFALAR" not in result
    assert "TRD210826F19" not in result


def test_cut_holdings_before_roman_ix_portfolio_transactions():
    text = """
III-FON PORTFÖY DEĞERİ
KİRA SERTİFİKALARI
SAFE HOLDING ROW
IX-PORTFÖYE ALIŞLAR
TRD200827F19 HAZINE 20/08/27 21/08/26 100,000 1.700.000,00 1.700.000,00
"""
    result = _cut_holdings_body(text)
    assert "SAFE HOLDING ROW" in result
    assert "IX-PORTFÖYE ALIŞLAR" not in result
    assert "TRD200827F19" not in result
