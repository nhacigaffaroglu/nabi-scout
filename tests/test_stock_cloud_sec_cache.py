from __future__ import annotations

from pathlib import Path

from services.scanner_v4_engine import ScannerV4Engine


class FakeCache:
    def __init__(self):
        self.calls = []

    def store_if_new(self, **kwargs):
        self.calls.append(kwargs)
        return object(), True


class BrokenCache:
    def store_if_new(self, **_kwargs):
        raise RuntimeError("disk unavailable")


def test_scanner_cache_capture_reuses_already_fetched_payload():
    cache = FakeCache()
    scanner = ScannerV4Engine(
        object(),
        object(),
        sec_company_facts_cache=cache,
    )
    payload = {"cik": "0001108524", "facts": {"us-gaap": {}}}

    status, error = scanner._cache_sec_company_facts(
        symbol="crm",
        cik="1108524",
        payload=payload,
    )

    assert status == "OK"
    assert error is None
    assert len(cache.calls) == 1
    assert cache.calls[0]["symbol"] == "CRM"
    assert cache.calls[0]["cik"] == "1108524"
    assert cache.calls[0]["raw_payload"] == payload


def test_scanner_without_cache_does_not_require_persistence():
    scanner = ScannerV4Engine(object(), object())
    status, error = scanner._cache_sec_company_facts(
        symbol="CRM",
        cik="1108524",
        payload={"facts": {}},
    )
    assert status is None
    assert error is None


def test_cache_failure_is_reportable_without_second_provider_path():
    scanner = ScannerV4Engine(
        object(),
        object(),
        sec_company_facts_cache=BrokenCache(),
    )
    status, error = scanner._cache_sec_company_facts(
        symbol="CRM",
        cik="1108524",
        payload={"facts": {}},
    )
    assert status == "ERİŞİLEMEDİ"
    assert "disk unavailable" in error


def test_daily_scan_wires_persistent_sec_cache_into_scanner():
    source = Path("scripts/run_daily_scan.py").read_text(encoding="utf-8")
    assert "sec_cache = SecCompanyFactsCache()" in source
    assert "sec_company_facts_cache=sec_cache" in source
    assert "engine=scanner" in source


def test_daily_scan_workflow_restores_and_saves_sec_cache():
    source = Path(".github/workflows/daily_scan.yml").read_text(
        encoding="utf-8"
    )
    assert "actions/cache/restore@v4" in source
    assert "actions/cache/save@v4" in source
    assert "data/private/sec_company_facts" in source
    assert "sec-company-facts-${{ github.ref_name }}-${{ github.run_id }}" in source


def test_us_si_schedule_remains_disabled():
    source = Path(".github/workflows/daily_scan.yml").read_text(
        encoding="utf-8"
    )
    assert "run_us_security_intelligence_refresh.py" not in source
