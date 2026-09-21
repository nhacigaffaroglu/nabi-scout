from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from services.fund_product_contract import IDENTITY_RESOLVED
from services.official_kap_pdr import PDR_PARSER_VERSION
from services.turkiye_fund_broad_capture import (
    _latest_applicable_row,
    _pack_is_reusable,
    capture_universe,
)
from services.turkiye_fund_source_capture import (
    OfficialCaptureSession,
)
from services.turkiye_fund_universe_contract import (
    TEFAS_STATUS_ACTIVE,
)


DAY = date(2026, 9, 20)


def _identity():
    return SimpleNamespace(
        fund_code="AAA",
        fund_name="AAA KATILIM FONU",
        founder=None,
        isin=None,
        tefas_status=TEFAS_STATUS_ACTIVE,
        kap_disclosure_index=None,
        pdr_year=2026,
        pdr_period=8,
    )


def _catalog_row():
    return {
        "fundCode": "AAA",
        "kapTitle": "AAA KATILIM FONU",
        "year": 2026,
        "period": 8,
        "publishDate": "03.09.2026 10:00:00",
        "disclosureIndex": 123456,
        "disclosureClass": "DG",
        "subject": "Portföy Dağılım Raporu",
    }


def _pack(period="2026-07"):
    return {
        "fund_code": "AAA",
        "evidence_recovery_version": 9,
        "production_persist": False,
        "identity_status": IDENTITY_RESOLVED,
        "documents": {
            "BILGI_FORMU": {
                "file_oid": "ybf-oid",
            },
        },
        "pdr_file_oid": "pdr-oid",
        "pdr_period": period,
        "pdr_parser_version": PDR_PARSER_VERSION,
        "review_reasons": [],
    }


def test_fixture_is_real_pdr_catalog_shape():
    latest = _latest_applicable_row(
        (_catalog_row(),),
        "AAA",
        DAY,
    )

    assert latest is not None
    assert latest["period"] == 8


def test_stale_pdr_period_is_not_reusable():
    assert not _pack_is_reusable(
        _pack("2026-07"),
        _identity(),
        expected_pdr_period="2026-08",
    )


def test_current_pdr_period_remains_reusable():
    assert _pack_is_reusable(
        _pack("2026-08"),
        _identity(),
        expected_pdr_period="2026-08",
    )


def test_newer_local_pdr_is_not_downgraded():
    assert _pack_is_reusable(
        _pack("2026-09"),
        _identity(),
        expected_pdr_period="2026-08",
    )


def test_missing_pdr_period_keeps_existing_policy():
    pack = _pack("2026-08")
    pack.pop("pdr_period")
    pack.pop("pdr_file_oid")
    pack.pop("pdr_parser_version")

    assert _pack_is_reusable(
        pack,
        _identity(),
        expected_pdr_period="2026-08",
    )


def test_capture_universe_recaptures_stale_pack():
    identity = _identity()
    catalog_row = _catalog_row()

    calls = []

    def fake_capture(row, **kwargs):
        calls.append(row.fund_code)

        return {
            **_pack("2026-08"),
            "errors": [],
        }

    session = OfficialCaptureSession(
        live=False,
        sleep=lambda _s: None,
        min_gap_sec=0,
    )

    with patch(
        "services.turkiye_fund_broad_capture.read_evidence_pack",
        return_value=_pack("2026-07"),
    ), patch(
        "services.turkiye_fund_broad_capture.capture_one_fund",
        side_effect=fake_capture,
    ):
        packs, stats = capture_universe(
            (identity,),
            catalog_rows=(catalog_row,),
            session=session,
            as_of=DAY,
            resume=True,
            fetch_prices=False,
            allow_ocr=False,
        )

    assert calls == ["AAA"]
    assert packs["AAA"]["pdr_period"] == "2026-08"
    assert stats.funds_attempted == 1
    assert stats.skipped_unchanged == 0
