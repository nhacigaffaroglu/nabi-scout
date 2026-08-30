"""Captured official SP Funds public excerpts.

Single source for product HTML used by the official provider and tests.
Do not add ticker-to-layer maps here.
"""

from __future__ import annotations

SPUS_PRODUCT_HTML = """
# The SP Funds S&P 500 Sharia Industry Exclusions ETF
SPUS is an ETF offering Sharia-compliant exposure. Adhering to AAOIFI guidelines.
### Tracking the S&P 500 Sharia Industry Exclusions Index
| Fund Inception | 12/29/2020 |
| Ticker | SPUS |
| Primary Exchange | NYSE |
| CUSIP | 886364801 |
| Expense Ratio* | 0.45% |
| Net Assets | $3154.90m |
| NAV | $59.27 |
| Closing Price | $59.28 |
| 08/26/2026 | 08/26/2026 | 08/27/2026 | 0.0260 |
### Certificate of Sharia Accreditation
### Sharia Auditor Report
"""

SPSK_PRODUCT_HTML = """
# The SP Funds Dow Jones Global Sukuk ETF
SPSK tracks Sharia-compliant sukuk and aligns with AAOIFI Sharia-compliant guidelines.
### Tracks the Dow Jones Sukuk Total Return Index
| Fund Inception | 12/27/2019 |
| Ticker | SPSK |
| Primary Exchange | NYSE |
| CUSIP | 886364702 |
| Expense Ratio* | 0.50% |
| Net Assets | $662.21m |
| NAV | $17.91 |
| Closing Price | $17.92 |
### Certificate of Sharia Accreditation
### Sharia Auditor Report
"""

SPRE_PRODUCT_HTML = """
# The SP Funds S&P Global REIT Sharia ETF
SPRE is a Sharia-compliant ETF that invests in global real estate per AAOIFI principles.
The S&P Global REIT Shariah Index is the official benchmark.
| Fund Inception | 12/29/2020 |
| Ticker | SPRE |
| Primary Exchange | NYSE |
| CUSIP | 886364769 |
| Expense Ratio* | 0.50% |
| Net Assets | $200.00m |
| NAV | $21.50 |
| Closing Price | $21.53 |
### Certificate of Sharia Accreditation
### Sharia Auditor Report
"""

SPWO_PRODUCT_HTML = """
# The SP Funds S&P World (ex-US) ETF
SPWO tracks sharia-compliant stocks from developed and emerging markets outside the US, per AAOIFI principles.
The S&P DM Ex-U.S. & EM 50/50 Shariah Index is the official benchmark.
| Fund Inception | 12/29/2020 |
| Ticker | SPUS |
| Primary Exchange | NYSE |
| CUSIP | 84612A200 |
| Expense Ratio* | 0.45% |
| Net Assets | $223.62m |
| NAV | $33.63 |
| Closing Price | $33.76 |
### Certificate of Sharia Accreditation
### Sharia Auditor Report
"""

PURIFICATION_HTML = """
These purification factors are calculated quarterly.
| Date | SPUS | SPRE | SPTE | SPWO |
| Q1 2026 | 1.81% | 0.52% | 2.27% | 1.55% |
| Q4 2025 | 1.97% | 0.56% | 2.50% | 1.91% |
SPSK does not require purification because Sukuk are Sharia-compliant by definition
The purification factors are determined using a methodology developed by ShariaPortfolio in accordance with the Accounting and Auditing Organization for Islamic Financial Institutions (AAOIFI) guidelines.
"""

PRODUCT_HTML = {
    "SPUS": SPUS_PRODUCT_HTML,
    "SPSK": SPSK_PRODUCT_HTML,
    "SPRE": SPRE_PRODUCT_HTML,
    "SPWO": SPWO_PRODUCT_HTML,
}
