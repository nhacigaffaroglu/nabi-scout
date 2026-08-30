"""Captured public Borsa Katılım Tüm CSV excerpt. Not a live feed."""

from __future__ import annotations

FIXTURE_DISCLAIMER = (
    "TEST-ONLY captured public Borsa Istanbul Katılım constituents excerpt. "
    "Not a live feed and not a Participation verdict."
)

# Official public URL used by https://www.borsaistanbul.com/katilim-finans
BORSA_KATILIM_CSV_URL = "https://www.borsaistanbul.com/datum/hisse_endeks_katilim_ds.csv"

# Observed public disclosure ids for the 1G pilot. Not production special cases.
PILOT_KAFIF_DISCLOSURES = {
    "ASELS": "1643144",
    "BIMAS": "1651659",
    "TUPRS": "1643837",
}


def compact_katilim_csv() -> str:
    return (
        "BILESEN KODU;BULTEN_ADI;ENDEKS KODU;ENDEKS ADI;ENDEKS INGILIZCE ADI;TARIH(GG/AA/YYYY)\r\n"
        "CONSTITUENT CODE;CONSTITUENT NAME;INDEX CODE;INDEX NAME IN TURKISH;INDEX NAME IN ENGLISH;DATE(DD/MM/YYYY)\r\n"
        "ASELS.E;ASELSAN;XK030;BIST KATILIM 30;BIST PARTICIPATION 30;31/08/2026\r\n"
        "ASELS.E;ASELSAN;XKTUM;BIST KATILIM TUM;BIST PARTICIPATION ALL;31/08/2026\r\n"
        "BIMAS.E;BIM MAGAZALAR;XKTUM;BIST KATILIM TUM;BIST PARTICIPATION ALL;31/08/2026\r\n"
        "TUPRS.E;TUPRAS;XKTUM;BIST KATILIM TUM;BIST PARTICIPATION ALL;31/08/2026\r\n"
        "XXXXX.E;NOT A PILOT;XK100;BIST KATILIM 100;BIST PARTICIPATION 100;31/08/2026\r\n"
    )
