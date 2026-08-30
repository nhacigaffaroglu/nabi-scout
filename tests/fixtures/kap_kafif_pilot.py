"""Captured public KAP KAFİF HTML excerpts. Not live issuer authority after capture."""

from __future__ import annotations

FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public KAP KAFİF HTML excerpt for parser regression. "
    "Not a live feed and not a Participation verdict."
)


def _summary_row(question: str, answer: str) -> str:
    return (
        f'<tr class="font15"><td><div class="font15">{question}</div></td>'
        f'<td class="txtCenter"><div class="gwt-HTML">{answer}</div></td></tr>'
    )


def compact_kafif_html(
    *,
    issuer: str = "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.",
    symbol: str = "ASELS",
    submitted: str = "04.08.202618:43:14",
    year: str = "2026",
    period: str = "6 Aylık",
    unit: str = "1.000 TL",
    consolidation: str = "Konsolide",
    q1: str = "HAYIR",
    q2: str = "HAYIR",
    q3: str = "HAYIR",
    q4: str = "HAYIR",
    income: str = "4,14",
    assets: str = "12,95",
    debt: str = "13,9",
) -> str:
    return f"""
<html><body>
<div>Gönderim Tarihi</div><div>{submitted}</div>
<div>Bildirim Tipi</div><div>DG</div>
<div>Yıl</div><div>{year}</div>
<div>Periyot</div><div>{period}</div>
<h1>{issuer}</h1>
<div>{symbol}</div>
<div>Katılım Finansı İlkeleri Bilgi Formu</div>
<table class="tbl_KFIF-General-Info-Form">
<tr><td>ÖZET BİLGİLER</td></tr>
{_summary_row("Sunum Para Birimi", unit)}
{_summary_row("Verilerin Ait Olduğu Finansal Tablo Yılı / Dönemi", f"{year} / {period}")}
{_summary_row("Finansal Tablo Niteliği", consolidation)}
{_summary_row("1) Şirketin kendisi, tüzel kişi ortakları veya iştiraklerinin esas sözleşmesinde yer alan faaliyet alanları arasında Katılım Finansı İlkelerine uygun olmayan faaliyet yer alıyor mu?", q1)}
{_summary_row("2) Şirket esas sözleşmesinde Katılım Finansı İlkelerine uygun olmayan imtiyaz bulunuyor mu?", q2)}
{_summary_row("3) Şirketin Standart madde 1.5 ve Rehber madde 1.D'de tanımlanan eylemleri desteklediğine ilişkin bir açıklama ve/veya karar bulunuyor mu?", q3)}
{_summary_row("4) Şirketin doğrudan Katılım Finansı İlkelerine aykırı kabul edilen faaliyetleri ve/veya geliri bulunuyor mu?", q4)}
{_summary_row("5) Şirketin Katılım Finansı İlkelerine Uygun Olmayan Gelirlerinin Oranı (%) [ (4B+4C-4D) / 4E ] * 100", income)}
{_summary_row("6) Şirketin Katılım Finansı İlkelerine Uygun Olmayan Varlıklarının Oranı (%) [ 5F-5G) / 5H ] * 100", assets)}
{_summary_row("7) Şirketin Katılım Finansı İlkelerine Uygun Olmayan Borçlarının Oranı (%) [ (6I-6J) / 5H ] * 100", debt)}
</table>
</body></html>
"""


def asels_kafif_html() -> str:
    return compact_kafif_html()


def bimas_kafif_html() -> str:
    return compact_kafif_html(
        issuer="BİM BİRLEŞİK MAĞAZALAR A.Ş.",
        symbol="BIMAS",
        submitted="17.08.202622:36:46",
        income="0",
        assets="0",
        debt="0",
    )


def tuprs_kafif_html() -> str:
    return compact_kafif_html(
        issuer="TÜPRAŞ-TÜRKİYE PETROL RAFİNERİLERİ A.Ş.",
        symbol="TUPRS",
        submitted="05.08.202618:22:23",
        income="2,24",
        assets="25",
        debt="7,52",
    )


def kafif_member_index_html() -> str:
    return """
<table>
<tr id="notification2">
<td><input id="1643144" type="checkbox"></td>
<td>04.08.2026</td><td>ASELS</td>
<td>Katılım Finansı İlkeleri Bilgi Formu</td>
<td>2026</td><td>6 Aylık</td>
</tr>
<tr id="notification51">
<td><input id="1561061" type="checkbox"></td>
<td>24.02.2026</td><td>ASELS</td>
<td>Katılım Finansı İlkeleri Bilgi Formu</td>
<td>2025</td><td>Yıllık</td>
</tr>
</table>
"""
