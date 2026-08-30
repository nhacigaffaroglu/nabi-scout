"""Captured official N-PORT identity snippets for the four pilot funds.

Period facts only. Holdings lists are omitted. This is not a crawler cache.
"""

from __future__ import annotations

SPUS_NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <accessionNumber>0002000324-26-003242</accessionNumber>
    <filerInfo><filer><issuerCredentials><cik>0001742912</cik></issuerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>Tidal Trust I</regName>
      <regFileNumber>811-23377</regFileNumber>
      <seriesId>S000067283</seriesId>
      <seriesName>SP Funds S&amp;P 500 Sharia Industry Exclusions ETF</seriesName>
      <classId>C000216395</classId>
      <repPdEnded>2026-05-31</repPdEnded>
    </genInfo>
    <fundInfo>
      <totAssets>2724959165.26</totAssets>
      <netAssets>2723971002.59</netAssets>
    </fundInfo>
  </formData>
</edgarSubmission>
"""

SPSK_NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <accessionNumber>0002000324-26-003239</accessionNumber>
    <filerInfo><filer><issuerCredentials><cik>0001742912</cik></issuerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>Tidal Trust I</regName>
      <regFileNumber>811-23377</regFileNumber>
      <seriesId>S000067282</seriesId>
      <seriesName>SP Funds Dow Jones Global Sukuk ETF</seriesName>
      <classId>C000216394</classId>
      <repPdEnded>2026-05-31</repPdEnded>
    </genInfo>
    <fundInfo>
      <totAssets>533011694.4</totAssets>
      <netAssets>530824412.05</netAssets>
    </fundInfo>
  </formData>
</edgarSubmission>
"""

SPRE_NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <accessionNumber>0002000324-26-003236</accessionNumber>
    <filerInfo><filer><issuerCredentials><cik>0001742912</cik></issuerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>Tidal Trust I</regName>
      <regFileNumber>811-23377</regFileNumber>
      <seriesId>S000070461</seriesId>
      <seriesName>SP Funds S&amp;P Global REIT Sharia ETF</seriesName>
      <classId>C000223966</classId>
      <repPdEnded>2026-05-31</repPdEnded>
    </genInfo>
    <fundInfo>
      <totAssets>203455977.38</totAssets>
      <netAssets>203354098.26</netAssets>
    </fundInfo>
  </formData>
</edgarSubmission>
"""

SPWO_NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <accessionNumber>0000894189-26-018183</accessionNumber>
    <filerInfo><filer><issuerCredentials><cik>0001989916</cik></issuerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>SP Funds Trust</regName>
      <regFileNumber>811-23893</regFileNumber>
      <seriesId>S000083496</seriesId>
      <seriesName>SP Funds S&amp;P World (ex-US) ETF</seriesName>
      <classId>C000247153</classId>
      <repPdEnded>2026-04-30</repPdEnded>
    </genInfo>
    <fundInfo>
      <totAssets>156025414.89</totAssets>
      <netAssets>155922708.73</netAssets>
    </fundInfo>
  </formData>
</edgarSubmission>
"""

NPORT_XML = {
    "SPUS": SPUS_NPORT_XML,
    "SPSK": SPSK_NPORT_XML,
    "SPRE": SPRE_NPORT_XML,
    "SPWO": SPWO_NPORT_XML,
}

# SPUS period net assets are from the official 2026-05-31 N-PORT.
# SPSK/SPRE/SPWO period totals below are identity fixtures only unless noted.
NPORT_FIXTURE_NOTES = {
    "SPUS": "official_nport_period_2026-05-31",
    "SPSK": "official_nport_period_2026-05-31",
    "SPRE": "official_nport_period_2026-05-31",
    "SPWO": "official_nport_period_2026-04-30",
}
