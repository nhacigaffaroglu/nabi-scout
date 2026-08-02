from __future__ import annotations
from services.investment_thesis_engine import build_investment_thesis
from services.scanner_v7_engine import ScannerV7Engine

class ScannerV8Engine(ScannerV7Engine):
    def analyze(self, **kwargs):
        result = super().analyze(**kwargs)
        if result.get("excluded"):
            return result
        candidate = result["candidate"]
        candidate.update(build_investment_thesis(candidate))
        candidate["scanner_version"] = "Scanner v8"
        return result
