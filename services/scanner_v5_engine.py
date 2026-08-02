from __future__ import annotations
from services.advanced_metrics import calculate
from services.investment_memo import build
from services.scanner_v4_engine import ScannerV4Engine

class ScannerV5Engine(ScannerV4Engine):
    def analyze(self, **kwargs):
        result = super().analyze(**kwargs)
        if result.get("excluded"):
            return result

        candidate = result["candidate"]
        candidate.update(calculate(candidate))
        candidate.update(build(candidate))
        candidate["scanner_version"] = "Scanner v5"
        return result
