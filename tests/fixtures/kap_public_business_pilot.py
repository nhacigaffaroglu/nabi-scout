"""Captured official KAP note excerpts. Not live issuer authority after capture."""

from __future__ import annotations


FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured official KAP note excerpt for parser regression. "
    "Not a live feed and not a Participation verdict."
)

PILOT_PUBLIC_BUSINESS_REPORTS = {
    "ASELS": "1643141",
    "BIMAS": "1651656",
    "TUPRS": "1643116",
}

ASELS_ACTIVITY_REPORT_ID = "1643140"
BIMAS_ACTIVITY_REPORT_ID = "1651657"
TUPRS_ACTIVITY_REPORT_ID = "1643117"


def html_without_segment_taxonomy() -> str:
    return """
    <div class="taxonomy-field-name">ifrs-full_Revenue|</div>
    <div class="taxonomy-field-name">ifrs-full_CashAndCashEquivalents|</div>
    <div class="taxonomy-field-name">ifrs-full_CurrentTradeReceivables|</div>
    <div class="taxonomy-field-name">ifrs-full_LongtermBorrowings|</div>
    <div class="taxonomy-field-name">kap-fr_RevenueFromFinanceSectorOperations|</div>
    <div class="taxonomy-field-name">kap-fr_OtherCurrentFinancialInvestments|</div>
    """


def html_with_unverified_segment_taxonomy() -> str:
    return (
        html_without_segment_taxonomy()
        + '<div class="taxonomy-field-name">ifrs-full_RevenueFromExternalCustomers|</div>'
    )


def asels_official_notes() -> str:
    return """
    (Tüm tutarlar aksi belirtilmedikçe Bin Türk Lirası'nın (“TL”) 30 Haziran 2026
    tarihindeki satın alma gücü cinsinden ifade edilmiştir.)
    14. HASILAT VE SATIŞLARIN MALİYETİ
    a) Hasılat 1 Ocak- 30 Haziran 2026
    Yurt içi satışlar 73.279.282
    Yurt dışı satışlar 15.214.970
    88.494.252
    """


def bimas_official_notes() -> str:
    return """
    (Tutarlar aksi belirtilmedikçe Bin Türk Lirası (“TL”) olarak, 30 Haziran 2026
    tarihi itibarıyla satın alma gücü esasına göre ifade edilmiştir.)
    Hasılat 18 449.695.235 221.902.578 409.303.226 202.425.831
    3. Bölümlere Göre Raporlama
    Bu nedenle, TFRS 8, “Faaliyet Bölümlerindeki ilgili hükümler doğrultusunda,
    Grup’un, tek bir raporlanabilecek faaliyet bölümü bulunmakta olup, finansal
    bilgiler faaliyet bölümlerine göre raporlanmamıştır.
    """


def tuprs_official_notes() -> str:
    return """
    (Tutarlar aksi belirtilmedikçe, Türk Lirasının 30 Haziran 2026 tarihindeki
    satın alma gücü cinsinden bin Türk Lirası ("TL") olarak ifade edilmiştir.)
    4. Bölümlere göre raporlama
    Grup yönetimi, Tüpraş’ın raporlanabilir bölümlerini rafinaj ve elektrik
    sektörleri olarak tanımlamıştır.
    1 Ocak- 30 Haziran 2026 Rafinaj Elektrik Konsolide Toplam
    Hasılat 659.045.615 3.742.395 662.788.010
    1 Nisan- 30 Haziran 2026 Rafinaj Elektrik Konsolide Toplam
    Hasılat 384.603.774 1.816.461 386.420.235
    """


def remainder_notes() -> str:
    return """
    Bin Türk Lirası
    1 Ocak- 30 Haziran 2026 Alpha Beta Konsolide Toplam
    Hasılat 80.000.000 10.000.000 100.000.000
    """


def unknown_named_notes() -> str:
    return """
    Bin Türk Lirası
    1 Ocak- 30 Haziran 2026 CasinoBank Konsolide Toplam
    Hasılat 100.000.000 100.000.000
    """
