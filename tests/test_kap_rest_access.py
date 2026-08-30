from __future__ import annotations

import unittest
from pathlib import Path

from services.kap_document_parser import raw_lines_from_handoff
from services.kap_financial_bridge import (
    KapIdentityError,
    build_kap_normalized_bundle,
    is_us_symbol_blocked_from_kap,
)
from services.kap_financial_contract import KAP_ACCESS_CREDENTIAL_BLOCKED, resolve_kap_financial_access
from services.kap_rest_client import (
    KapRestClient,
    KapRestUnavailable,
    build_official_document_handoff,
    classify_financial_disclosure,
    detail_from_payload,
)
from services.kap_rest_config import KAP_API_KEY_ENV, KAP_BASE_URL_ENV, KapRestConfig, load_kap_rest_config
from services.kap_rest_contract import (
    CLASSIFICATION_FINANCIAL_CANDIDATE,
    CLASSIFICATION_NOT_CLASSIFIED,
    DOCUMENT_STRUCTURED_PAYLOAD,
    DOCUMENT_UNAVAILABLE,
    KAP_DOCUMENTED_SERVICES,
    KAP_FINANCIAL_DISCLOSURE_PATH,
    KAP_SERVICE_DISCLOSURE_DETAIL,
    KAP_SERVICE_DISCLOSURES,
    KAP_SERVICE_DOWNLOAD_ATTACHMENT,
    LIMITATION_ATTACHMENT_MISSING,
    LIMITATION_CONFIG_MISSING,
    LIMITATION_NOT_CLASSIFIED,
    LIMITATION_TRANSPORT_UNAVAILABLE,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY, RESOLUTION_RESOLVED, SOURCE_BIST
from services.security_master_service import SecurityMasterService
from services.signal_disclosure_adapters import KapDisclosureAdapter
from services.signal_ingestion_policy import ADAPTER_SEC
from tests.fixtures.kap_rest_pilot import (
    FIXTURE_DISCLAIMER,
    MemoryKapTransport,
    missing_attachment_detail,
    pilot_transport,
    unknown_detail,
)


CLIENT = Path("services/kap_rest_client.py")
PARSER = Path("services/kap_document_parser.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")


def _configured_client(transport=None) -> KapRestClient:
    return KapRestClient(
        config=KapRestConfig(base_url="https://example.invalid", api_key="test-not-live"),
        transport=transport,
    )


class KapConfigTests(unittest.TestCase):
    def test_missing_config_is_unavailable(self) -> None:
        config = load_kap_rest_config(environ={})
        self.assertFalse(config.available)
        self.assertEqual(config.base_url, "")
        self.assertEqual(config.api_key, "")
        client = KapRestClient(config=config, transport=pilot_transport())
        self.assertFalse(client.available)
        with self.assertRaises(KapRestUnavailable) as raised:
            client.list_disclosures(symbol="ASELS")
        self.assertEqual(str(raised.exception), LIMITATION_CONFIG_MISSING)
        self.assertEqual(client.call_count, 0)

    def test_config_without_transport_does_not_call(self) -> None:
        client = _configured_client(transport=None)
        self.assertFalse(client.available)
        with self.assertRaises(KapRestUnavailable) as raised:
            client.list_disclosures(symbol="ASELS")
        self.assertEqual(str(raised.exception), LIMITATION_TRANSPORT_UNAVAILABLE)
        self.assertEqual(client.call_count, 0)

    def test_env_placeholders_have_no_default_url(self) -> None:
        self.assertEqual(KAP_BASE_URL_ENV, "NABI_KAP_BASE_URL")
        self.assertEqual(KAP_API_KEY_ENV, "NABI_KAP_API_KEY")
        source = Path("services/kap_rest_config.py").read_text(encoding="utf-8")
        self.assertNotIn("kap.org.tr", source)
        self.assertNotIn("https://", source)


class KapClientDtoTests(unittest.TestCase):
    def test_list_detail_and_attachment_dtos(self) -> None:
        client = _configured_client(pilot_transport())
        rows = client.list_disclosures(symbol="ASELS")
        self.assertEqual(rows[0].disclosure_id, "ASELS-FIN")
        self.assertEqual(rows[0].symbol, "ASELS")
        detail = client.get_disclosure_detail(disclosure_id="ASELS-FIN")
        self.assertEqual(detail.disclosure_id, "ASELS-FIN")
        self.assertTrue(detail.explicit_financial_report_candidate)
        self.assertTrue(detail.structured_raw_lines)
        missing = client.download_attachment(attachment_ref="missing-ref")
        self.assertFalse(missing.available)
        self.assertEqual(missing.limitation, LIMITATION_ATTACHMENT_MISSING)
        present = client.download_attachment(attachment_ref="ASELS-ATT")
        self.assertTrue(present.available)
        self.assertGreater(client.call_count, 0)

    def test_transport_failure_produces_no_facts(self) -> None:
        client = _configured_client(MemoryKapTransport({}, fail=True))
        with self.assertRaises(Exception):
            client.list_disclosures(symbol="ASELS")
        self.assertEqual(client.call_count, 1)

    def test_documented_services_only_no_invented_url(self) -> None:
        self.assertEqual(
            KAP_FINANCIAL_DISCLOSURE_PATH,
            (KAP_SERVICE_DISCLOSURES, KAP_SERVICE_DISCLOSURE_DETAIL, KAP_SERVICE_DOWNLOAD_ATTACHMENT),
        )
        self.assertIn("funds", KAP_DOCUMENTED_SERVICES)
        source = CLIENT.read_text(encoding="utf-8")
        self.assertNotIn("kap.org.tr", source)
        self.assertNotIn("normalize_raw_line", source)
        self.assertNotIn("KAP_ACCOUNT_CODE_MAP", source)
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)


class ClassificationAndHandoffTests(unittest.TestCase):
    def test_unknown_disclosure_is_not_classified(self) -> None:
        detail = detail_from_payload(unknown_detail("TUPRS", disclosure_id="TUPRS-UNK"))
        self.assertEqual(classify_financial_disclosure(detail), CLASSIFICATION_NOT_CLASSIFIED)
        handoff = build_official_document_handoff(symbol="TUPRS", detail=detail)
        self.assertEqual(handoff.classification, CLASSIFICATION_NOT_CLASSIFIED)
        self.assertEqual(handoff.document_kind, DOCUMENT_UNAVAILABLE)
        self.assertEqual(handoff.limitation, LIMITATION_NOT_CLASSIFIED)
        self.assertEqual(raw_lines_from_handoff(handoff), ())

    def test_headline_is_not_used_for_classification(self) -> None:
        detail = detail_from_payload(
            {
                "disclosure_id": "X",
                "title": "Finansal Rapor / Financial Statements",
            }
        )
        self.assertEqual(classify_financial_disclosure(detail), CLASSIFICATION_NOT_CLASSIFIED)

    def test_missing_attachment_produces_no_lines(self) -> None:
        detail = detail_from_payload(missing_attachment_detail("ASELS", disclosure_id="ASELS-MISS"))
        handoff = build_official_document_handoff(symbol="ASELS", detail=detail)
        self.assertEqual(handoff.limitation, LIMITATION_ATTACHMENT_MISSING)
        self.assertEqual(raw_lines_from_handoff(handoff), ())

    def test_handoff_does_not_normalize(self) -> None:
        parser = PARSER.read_text(encoding="utf-8")
        self.assertNotIn("normalize_kap_lines", parser)
        self.assertNotIn("normalized_value", parser)
        self.assertIn("KapRawFinancialLine", parser)


class PipelineAndRegressionTests(unittest.TestCase):
    def test_bist_1b_accepts_classified_handoff(self) -> None:
        client = _configured_client(pilot_transport())
        detail = client.get_disclosure_detail(disclosure_id="ASELS-FIN")
        handoff = build_official_document_handoff(symbol="ASELS", detail=detail)
        self.assertEqual(handoff.document_kind, DOCUMENT_STRUCTURED_PAYLOAD)
        self.assertEqual(handoff.classification, CLASSIFICATION_FINANCIAL_CANDIDATE)
        lines = raw_lines_from_handoff(handoff)
        self.assertTrue(lines)
        bundle = build_kap_normalized_bundle("ASELS", lines)
        facts = SecurityFactsService().build(
            "ASELS", kap_financials=bundle, allow_sec_cache_replay=False
        )
        self.assertEqual(facts.currency, "TRY")
        self.assertIsNotNone(facts.revenue)

    def test_pilot_identity_and_unknown_tuprs(self) -> None:
        master = SecurityMasterService()
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            resolution = master.resolve_security(symbol)
            self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
            self.assertEqual(resolution.source, SOURCE_BIST)
        client = _configured_client(pilot_transport())
        tuprs = build_official_document_handoff(
            symbol="TUPRS",
            detail=client.get_disclosure_detail(disclosure_id="TUPRS-UNK"),
        )
        self.assertEqual(raw_lines_from_handoff(tuprs), ())

    def test_us_isolation_and_signal_adapter_unchanged(self) -> None:
        self.assertTrue(is_us_symbol_blocked_from_kap("AAPL"))
        self.assertTrue(is_us_symbol_blocked_from_kap("CRM"))
        self.assertFalse(KapDisclosureAdapter.available)
        with self.assertRaises(NotImplementedError):
            KapDisclosureAdapter().raw_from_disclosure()
        with self.assertRaises(KapIdentityError):
            client = _configured_client(pilot_transport())
            detail = client.get_disclosure_detail(disclosure_id="ASELS-FIN")
            handoff = build_official_document_handoff(symbol="AAPL", detail=detail)
            build_kap_normalized_bundle("AAPL", raw_lines_from_handoff(handoff))
        facts = SecurityFactsService().build(
            "CRM",
            sec_financials={"revenue": 100, "financial_currency": "USD"},
            kap_financials={"revenue": 1, "currency": "TRY"},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 100)
        self.assertEqual(facts.currency, "USD")
        self.assertEqual(ADAPTER_SEC, "sec")

    def test_8e_still_unsupported(self) -> None:
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertIn("BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))

    def test_access_status_and_fixture_disclaimer(self) -> None:
        status = resolve_kap_financial_access()
        self.assertEqual(status.status, KAP_ACCESS_CREDENTIAL_BLOCKED)
        self.assertFalse(status.live_calls_allowed)
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertIn("Not official KAP", FIXTURE_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
