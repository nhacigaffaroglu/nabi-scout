from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from services.turkiye_fund_scanner import _runtime_pdr_quality


@dataclass(frozen=True)
class _Holding:
    asset_group: str
    portfolio_weight: float
    issuer_raw: str | None = None
    maturity_date: str | None = None
    currency: str | None = None
    isin: str | None = None


def test_runtime_pdr_quality_describes_current_object_without_mutation():
    holdings = (
        _Holding(
            asset_group="LEASE_CERTIFICATE",
            portfolio_weight=60.0,
            issuer_raw="Issuer A",
            maturity_date="2027-01-01",
            currency="TRY",
            isin="TR0000000001",
        ),
        _Holding(
            asset_group="PARTICIPATION_ACCOUNT",
            portfolio_weight=40.0,
            issuer_raw="Bank B",
            currency="TRY",
        ),
    )
    weights = SimpleNamespace(
        reported_weight_sum=100.0,
        known_weight=100.0,
        unknown_weight=0.0,
        weight_reconciled=True,
        renormalized=False,
    )
    file = SimpleNamespace(holdings=holdings, weights=weights)

    quality = _runtime_pdr_quality(file)

    assert quality["row_count"] == 2
    assert quality["reported_weight"] == 100.0
    assert quality["known_weight"] == 100.0
    assert quality["unknown_weight"] == 0.0
    assert quality["reconciliation"] is True
    assert quality["issuer_coverage"] == 1.0
    assert quality["maturity_coverage"] == 0.5
    assert quality["currency_coverage"] == 1.0
    assert quality["isin_coverage"] == 0.5
    assert quality["asset_groups"] == {
        "LEASE_CERTIFICATE": 60.0,
        "PARTICIPATION_ACCOUNT": 40.0,
    }
    assert quality["renormalized"] is False
    assert holdings[0].portfolio_weight == 60.0
    assert holdings[1].portfolio_weight == 40.0


def test_runtime_pdr_quality_none_is_empty():
    assert _runtime_pdr_quality(None) == {}


def test_scanner_source_keeps_observability_diagnostics_only():
    source = Path("services/turkiye_fund_scanner.py").read_text(
        encoding="utf-8"
    )

    assert "runtime_pdr_quality" in source
    assert "_runtime_pdr_quality(pdr)" in source
    assert 'raise ValueError("turkiye_fund_scanner_persist_refused")' in source
    assert "production_writes=()" in source
    assert "eight_e_calls=0" in source
    assert "new_money_calls=0" in source
    assert "trades=0" in source
    assert "portfolio_writes=0" in source
    assert "persist=False" in source
