from types import SimpleNamespace

import pytest

import services.official_kap_pdr as pdr
from services.official_kap_pdr_evidence import load_pdr_text


def test_elz_verified_section_iv_denominator_does_not_pollute_reconciliation():
    raw = load_pdr_text("ELZ")

    parsed = pdr.parse_kap_pdr_text(
        raw,
        fund_code="ELZ",
        report_period=None,
    )

    # Official Section III economic weights already reconcile on their own.
    assert parsed.weights.reported_weight_sum == pytest.approx(100.01)
    assert parsed.weights.weight_reconciled is True
    assert parsed.weights.renormalized is False

    # Section IV accounting rows remain available as raw official evidence.
    overlays = {
        row.security_name_raw: row.portfolio_weight
        for row in parsed.holdings
        if row.security_name_raw
        in {
            "HAZIR DEĞERLER",
            "ALACAKLAR",
            "BORÇLAR",
            "DİĞER VARLIKLAR",
        }
    }

    assert overlays["HAZIR DEĞERLER"] == pytest.approx(0.02)
    assert overlays["ALACAKLAR"] == pytest.approx(4.98)
    assert overlays["BORÇLAR"] == pytest.approx(-4.45)


def test_verified_section_iv_filter_is_fail_closed_and_generalized():
    helper = getattr(
        pdr,
        "_reconciliation_rows_for_verified_section_iv_accounting",
    )

    def row(name, weight, mv):
        return SimpleNamespace(
            security_name_raw=name,
            portfolio_weight=weight,
            market_value=mv,
        )

    economic = [
        row("AAA", 60.0, 600.0),
        row("BBB", 40.0, 400.0),
    ]

    accounting = [
        row("HAZIR DEĞERLER", 0.02, 0.2),
        row("ALACAKLAR", 4.98, 49.8),
        row("BORÇLAR", -4.45, 44.5),
    ]

    rows = economic + accounting

    verified = helper(
        "A. FON PORTFÖY DEĞERİ 1.000,00 %99,45",
        rows,
    )

    assert list(verified) == economic

    # Market-value mismatch -> no filtering.
    mismatch = helper(
        "A. FON PORTFÖY DEĞERİ 900,00 %99,45",
        rows,
    )

    assert list(mismatch) == rows

    # Already-reconciled combined total -> do not alter it.
    already_ok = [
        row("AAA", 60.0, 600.0),
        row("BBB", 39.0, 400.0),
        row("HAZIR DEĞERLER", 0.02, 0.2),
        row("ALACAKLAR", 0.20, 2.0),
        row("BORÇLAR", -0.10, 1.0),
    ]

    unchanged = helper(
        "A. FON PORTFÖY DEĞERİ 1.000,00 %99,45",
        already_ok,
    )

    assert list(unchanged) == already_ok
