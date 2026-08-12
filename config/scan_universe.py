SCAN_UNIVERSES = {
    "Katılım ETF 3": ["SPUS", "HLAL", "SPSK"],
    "Teknoloji 10": [
        "AAPL", "MSFT", "NVDA", "AVGO", "GOOGL",
        "META", "AMZN", "CRM", "TSM", "ASML",
    ],
    "Pilot 15": [
        "AAPL", "MSFT", "NVDA", "AVGO", "GOOGL",
        "AMZN", "META", "TSM", "ASML", "CRM",
        "SPUS", "HLAL", "SPSK", "JNJ", "XOM",
    ],
}

from config.participation_catalog import CONFIGURED_PARTICIPATION_CATALOG

# Backward-compatible alias for scan/fund imports.
PARTICIPATION_DEFAULTS = CONFIGURED_PARTICIPATION_CATALOG
