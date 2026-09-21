import pytest

from services.official_kap_pdr import (
    KapPdrError,
    parse_kap_pdr_text,
)


def test_transaction_only_capture_fails_closed():
    text = """
VII-PORTFÖYDEN SATIŞLAR

B) HAZİNE BONOSU VE DEVLET TAHVİLLERİ (SATIŞLAR)

XS3190527120 VAKIF KATILIM 14/10/30 18/08/26 104,368 260.919,97 250.000,00

VIII-İTFALAR

B) HAZİNE BONOSU VE DEVLET TAHVİLLERİ (ITFALAR)

TRD210826F19 HAZINE 21/08/26 21/08/26 1,007 1.000.000,00 1.000.000,00

IX-PORTFÖYE ALIŞLAR

B) HAZİNE BONOSU VE DEVLET TAHVİLLERİ (ALIŞLAR)

TRD200827F19 HAZINE 20/08/27 21/08/26 100,000 1.700.000,00 1.700.000,00
"""

    with pytest.raises(
        KapPdrError,
        match="transaction-only",
    ):
        parse_kap_pdr_text(
            text,
            fund_code="TST",
            report_period="2026-08",
        )
