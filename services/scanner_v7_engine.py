from __future__ import annotations

from services.research_intelligence_engine import enrich_research
from services.scanner_v5_engine import ScannerV5Engine


class ScannerV7Engine(ScannerV5Engine):
    def analyze(self, **kwargs):
        result = super().analyze(**kwargs)

        if result.get("excluded"):
            return result

        candidate = result["candidate"]
        enrich_research(
            candidate,
            errors=result.get("errors") or [],
        )
        candidate["scanner_version"] = "Scanner v7"
        return result
