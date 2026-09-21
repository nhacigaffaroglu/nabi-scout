from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.turkiye_fund_pdr_materializer import (
    materialize_kap_only_pdr_texts,
    select_kap_only_pdr_recovery_codes,
)
from services.turkiye_fund_universe_contract import (
    TEFAS_STATUS_ACTIVE,
)


DAY = date(2026, 9, 20)

ROW = {
    "fundCode": "ETF1",
    "year": 2026,
    "period": 8,
    "publishDate": "03.09.2026 10:00:00",
    "disclosureIndex": 123456,
}


def test_selects_missing_inactive_catalog_pdr_only():
    identities = (
        SimpleNamespace(
            fund_code="ETF1",
            tefas_status="INACTIVE",
        ),
        SimpleNamespace(
            fund_code="ACTIVE1",
            tefas_status=TEFAS_STATUS_ACTIVE,
        ),
    )

    rows = (
        ROW,
        {
            **ROW,
            "fundCode": "ACTIVE1",
            "disclosureIndex": 123457,
        },
    )

    with patch(
        "services.turkiye_fund_pdr_materializer.cached_pdr_text_path",
        return_value=None,
    ):
        selected = select_kap_only_pdr_recovery_codes(
            identities,
            rows,
            as_of=DAY,
        )

    assert selected == ("ETF1",)


def test_existing_cache_is_not_selected():
    identity = SimpleNamespace(
        fund_code="ETF1",
        tefas_status="INACTIVE",
    )

    with patch(
        "services.turkiye_fund_pdr_materializer.cached_pdr_text_path",
        return_value=Path("/tmp/ETF1_2026.08.txt"),
    ):
        selected = select_kap_only_pdr_recovery_codes(
            (identity,),
            (ROW,),
            as_of=DAY,
        )

    assert selected == ()


def test_materializes_valid_unreconciled_pdr_without_renormalizing():
    parsed = SimpleNamespace(
        holdings=(object(), object()),
        weights=SimpleNamespace(
            reported_weight_sum=93.4,
            weight_reconciled=False,
            renormalized=False,
        ),
    )

    recovery = {
        "text": "OFFICIAL PDR TEXT",
        "source_layer": "PDF_EMBEDDED_TEXT",
        "file_oid": "official-oid",
    }

    with patch(
        "services.turkiye_fund_pdr_materializer.cached_pdr_text_path",
        return_value=None,
    ), patch(
        "services.turkiye_fund_pdr_materializer.recover_official_document_text",
        return_value=recovery,
    ), patch(
        "services.turkiye_fund_pdr_materializer.parse_kap_pdr_text",
        return_value=parsed,
    ), patch(
        "services.turkiye_fund_pdr_materializer.write_cached_pdr_text",
        return_value=Path("/tmp/ETF1_2026.08.txt"),
    ) as writer:
        result = materialize_kap_only_pdr_texts(
            (ROW,),
            session=object(),
            as_of=DAY,
            fund_codes=("ETF1",),
        )

    assert result["ETF1"]["status"] == "MATERIALIZED"
    assert result["ETF1"]["reconciled"] is False
    assert result["ETF1"]["renormalized"] is False
    writer.assert_called_once()


def test_refuses_renormalized_parser_output():
    parsed = SimpleNamespace(
        holdings=(object(),),
        weights=SimpleNamespace(
            reported_weight_sum=100.0,
            weight_reconciled=True,
            renormalized=True,
        ),
    )

    with patch(
        "services.turkiye_fund_pdr_materializer.cached_pdr_text_path",
        return_value=None,
    ), patch(
        "services.turkiye_fund_pdr_materializer.recover_official_document_text",
        return_value={
            "text": "OFFICIAL PDR TEXT",
            "source_layer": "PDF_EMBEDDED_TEXT",
        },
    ), patch(
        "services.turkiye_fund_pdr_materializer.parse_kap_pdr_text",
        return_value=parsed,
    ), patch(
        "services.turkiye_fund_pdr_materializer.write_cached_pdr_text",
    ) as writer:
        result = materialize_kap_only_pdr_texts(
            (ROW,),
            session=object(),
            as_of=DAY,
            fund_codes=("ETF1",),
        )

    assert result["ETF1"]["status"] == "RENORMALIZED_REFUSED"
    writer.assert_not_called()
