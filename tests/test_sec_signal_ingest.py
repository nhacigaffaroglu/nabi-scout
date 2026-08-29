from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from repositories.signal_intelligence_repository import InMemorySignalIntelligenceRepository
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
from services.sec_eight_k_discovery import discover_recent_8k_filings, parse_sec_8k_items
from services.sec_eight_k_taxonomy import COMPANION_ITEMS, map_sec_8k_item, generic_8k_mapping
from services.security_intelligence_contract import SecurityFacts, SecurityParticipationContext
from services.security_intelligence_engine import evaluate_security_intelligence
from services.signal_disclosure_adapters import raw_inputs_from_8k_filing
from services.signal_intelligence_contract import (
    DIRECTION_NEGATIVE,
    DIRECTION_NEUTRAL,
    DIRECTION_UNKNOWN,
    EVENT_EARNINGS,
    EVENT_LEGAL_REGULATORY,
    EVENT_MANAGEMENT_CHANGE,
    EVENT_OTHER,
    EVENT_SEC_FILING,
    MATERIALITY_CRITICAL,
    MATERIALITY_LOW,
    MATERIALITY_MEDIUM,
    MATERIALITY_UNKNOWN,
    SUBTYPE_BANKRUPTCY,
    SUBTYPE_FORM_8K,
    TIER_1_PRIMARY,
    VERIFIED,
)
from services.signal_intelligence_engine import (
    authoritative_event_id,
    event_identity,
    evidence_identity,
    resolve_direction,
    resolve_materiality,
)
from services.signal_intelligence_fixtures import fixture_material_positive
from services.signal_intelligence_service import SignalIntelligenceService
from services.signal_sec_ingest_fixtures import (
    fixture_crm_multi_item_8k,
    fixture_crm_single_item_8k,
    fixture_crm_unknown_items_8k,
    submissions_from_rows,
)
from services.signal_sec_ingest_service import run_sec_signal_ingestion


ENGINE = Path("services/signal_intelligence_engine.py")
INGEST = Path("services/signal_sec_ingest_service.py")
DISCOVERY = Path("services/sec_eight_k_discovery.py")
ADAPTERS = Path("services/signal_disclosure_adapters.py")
TAXONOMY = Path("services/sec_eight_k_taxonomy.py")
RUNNER = Path("scripts/run_sec_signal_ingestion.py")


def _ingest(payload, *, as_of: date, lookback_days: int = 90, symbols=("CRM",), repo=None, **kwargs):
    store = repo or InMemorySignalIntelligenceRepository()
    report = run_sec_signal_ingestion(
        symbols,
        repo=store,
        submissions_by_symbol={"CRM": payload, **kwargs.pop("extra_submissions", {})},
        cik_by_symbol={"CRM": "1108524", **kwargs.pop("extra_ciks", {})},
        lookback_days=lookback_days,
        as_of=as_of,
        **kwargs,
    )
    return store, report


class SecDiscoveryTests(unittest.TestCase):
    def test_parses_well_formed_items_only(self) -> None:
        self.assertEqual(parse_sec_8k_items("2.02,9.01"), ("2.02", "9.01"))
        self.assertEqual(parse_sec_8k_items("Item 5.02; 8.01"), ("5.02", "8.01"))
        self.assertEqual(parse_sec_8k_items("Results of operations"), ())
        self.assertEqual(parse_sec_8k_items(""), ())

    def test_discovers_recent_8k_and_ignores_10k_and_old_filings(self) -> None:
        filings = discover_recent_8k_filings(
            fixture_crm_single_item_8k(),
            symbol="CRM",
            cik="1108524",
            lookback_days=90,
            as_of=date(2026, 3, 20),
        )
        self.assertEqual(len(filings), 1)
        filing = filings[0]
        self.assertEqual(filing.form, "8-K")
        self.assertEqual(filing.accession, "0001108524-26-000088")
        self.assertEqual(filing.filing_date, "2026-03-15")
        self.assertEqual(filing.items, ("2.02", "9.01"))
        self.assertIn("000110852426000088", filing.filing_url)
        self.assertTrue(filing.acceptance_at)

    def test_lookback_excludes_outside_window(self) -> None:
        filings = discover_recent_8k_filings(
            fixture_crm_single_item_8k(),
            symbol="CRM",
            cik="1108524",
            lookback_days=1,
            as_of=date(2026, 3, 20),
        )
        self.assertEqual(filings, ())


class SecTaxonomyTests(unittest.TestCase):
    def test_conservative_mapping_table(self) -> None:
        self.assertEqual(map_sec_8k_item("2.02"), (EVENT_EARNINGS, "ITEM_2_02"))
        self.assertEqual(map_sec_8k_item("5.02"), (EVENT_MANAGEMENT_CHANGE, "ITEM_5_02"))
        self.assertEqual(map_sec_8k_item("1.01"), (EVENT_OTHER, "ITEM_1_01"))
        self.assertEqual(map_sec_8k_item("8.01"), (EVENT_OTHER, "ITEM_8_01"))
        self.assertEqual(map_sec_8k_item("1.03"), (EVENT_LEGAL_REGULATORY, SUBTYPE_BANKRUPTCY))
        self.assertEqual(map_sec_8k_item("99.99"), (EVENT_OTHER, None))
        self.assertEqual(generic_8k_mapping(), (EVENT_SEC_FILING, SUBTYPE_FORM_8K))
        self.assertIn("9.01", COMPANION_ITEMS)

    def test_unknown_item_fail_closed_does_not_split(self) -> None:
        filings = discover_recent_8k_filings(
            fixture_crm_unknown_items_8k(),
            symbol="CRM",
            cik="1108524",
            lookback_days=30,
            as_of=date(2026, 8, 10),
        )
        raws = raw_inputs_from_8k_filing(filings[0])
        self.assertEqual(len(raws), 1)
        self.assertIsNone(raws[0].logical_event_key)
        self.assertEqual(raws[0].event_type, EVENT_SEC_FILING)
        self.assertEqual(raws[0].event_subtype, SUBTYPE_FORM_8K)


class SecIdentityTests(unittest.TestCase):
    def test_accession_is_authoritative_identity(self) -> None:
        filings = discover_recent_8k_filings(
            fixture_crm_single_item_8k(),
            symbol="CRM",
            cik="1108524",
            lookback_days=90,
            as_of=date(2026, 3, 20),
        )
        raw = raw_inputs_from_8k_filing(filings[0])[0]
        self.assertEqual(authoritative_event_id(raw), "0001108524-26-000088")
        self.assertEqual(raw.external_id, "0001108524-26-000088")
        self.assertEqual(raw.logical_event_key, "2.02")
        self.assertTrue(event_identity(raw).startswith("evt:"))

    def test_multi_item_same_accession_distinct_events(self) -> None:
        filings = discover_recent_8k_filings(
            fixture_crm_multi_item_8k(),
            symbol="CRM",
            cik="1108524",
            lookback_days=30,
            as_of=date(2026, 7, 2),
        )
        raws = raw_inputs_from_8k_filing(filings[0])
        self.assertEqual([item.logical_event_key for item in raws], ["2.02", "5.02"])
        self.assertEqual({item.authoritative_event_id for item in raws}, {"0001108524-26-000200"})
        self.assertNotEqual(event_identity(raws[0]), event_identity(raws[1]))
        self.assertNotEqual(evidence_identity(raws[0], event_identity(raws[0])), evidence_identity(raws[1], event_identity(raws[1])))


class SecVerificationMaterialityDirectionTests(unittest.TestCase):
    def test_sec_evidence_is_tier1_verified(self) -> None:
        _, report = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20))
        event = report.results[0].ingest_results[0].event
        self.assertEqual(event.source_authority, TIER_1_PRIMARY)
        self.assertEqual(event.verification_status, VERIFIED)
        self.assertEqual(event.event_type, EVENT_EARNINGS)
        self.assertEqual(event.materiality, MATERIALITY_MEDIUM)
        self.assertEqual(event.direction, DIRECTION_UNKNOWN)

    def test_existing_materiality_and_direction_rules_unchanged(self) -> None:
        self.assertEqual(
            resolve_materiality(
                event_type=EVENT_SEC_FILING,
                event_subtype=SUBTYPE_FORM_8K,
                verification=VERIFIED,
                authority=TIER_1_PRIMARY,
            )[0],
            MATERIALITY_MEDIUM,
        )
        self.assertEqual(
            resolve_materiality(
                event_type=EVENT_MANAGEMENT_CHANGE,
                event_subtype="ITEM_5_02",
                verification=VERIFIED,
                authority=TIER_1_PRIMARY,
            )[0],
            MATERIALITY_LOW,
        )
        self.assertEqual(
            resolve_materiality(
                event_type=EVENT_OTHER,
                event_subtype="ITEM_1_01",
                verification=VERIFIED,
                authority=TIER_1_PRIMARY,
            )[0],
            MATERIALITY_UNKNOWN,
        )
        self.assertEqual(
            resolve_materiality(
                event_type=EVENT_LEGAL_REGULATORY,
                event_subtype=SUBTYPE_BANKRUPTCY,
                verification=VERIFIED,
                authority=TIER_1_PRIMARY,
            )[0],
            MATERIALITY_CRITICAL,
        )
        self.assertEqual(resolve_direction(event_type=EVENT_SEC_FILING, event_subtype=SUBTYPE_FORM_8K), DIRECTION_NEUTRAL)
        self.assertEqual(resolve_direction(event_type=EVENT_MANAGEMENT_CHANGE, event_subtype="ITEM_5_02"), DIRECTION_UNKNOWN)
        self.assertEqual(resolve_direction(event_type=EVENT_LEGAL_REGULATORY, event_subtype=SUBTYPE_BANKRUPTCY), DIRECTION_NEGATIVE)

    def test_8k_is_not_inherently_high_or_signed(self) -> None:
        _, report = _ingest(fixture_crm_unknown_items_8k(), as_of=date(2026, 8, 10))
        event = report.results[0].ingest_results[0].event
        self.assertEqual(event.materiality, MATERIALITY_MEDIUM)
        self.assertEqual(event.direction, DIRECTION_NEUTRAL)
        self.assertNotEqual(event.materiality, "HIGH")


class SecIngestIdempotencyTests(unittest.TestCase):
    def test_single_item_ingest_and_replay(self) -> None:
        repo, first = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20))
        self.assertEqual(first.event_writes, 1)
        self.assertEqual(first.evidence_writes, 1)
        _, replay = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20), repo=repo)
        self.assertEqual(replay.event_writes, 0)
        self.assertEqual(replay.evidence_writes, 0)
        self.assertEqual(len(repo.events), 1)
        self.assertEqual(len(repo.evidence), 1)

    def test_multi_item_two_events_same_accession(self) -> None:
        repo, first = _ingest(fixture_crm_multi_item_8k(), as_of=date(2026, 7, 2))
        self.assertEqual(first.event_writes, 2)
        self.assertEqual(first.evidence_writes, 2)
        rows = first.results[0].ingest_results
        self.assertEqual(rows[0].event.authoritative_event_id, rows[1].event.authoritative_event_id)
        self.assertNotEqual(rows[0].event.logical_event_key, rows[1].event.logical_event_key)
        self.assertNotEqual(rows[0].event.event_id, rows[1].event.event_id)
        self.assertEqual({item.evidence.event_id for item in rows}, {item.event.event_id for item in rows})
        _, replay = _ingest(fixture_crm_multi_item_8k(), as_of=date(2026, 7, 2), repo=repo)
        self.assertEqual(replay.event_writes, 0)
        self.assertEqual(replay.evidence_writes, 0)

    def test_bounded_lookback_replay_does_not_pick_old_filing(self) -> None:
        _, report = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20), lookback_days=90)
        accessions = [item.accession for item in report.results[0].discovered]
        self.assertEqual(accessions, ["0001108524-26-000088"])

    def test_failure_isolation(self) -> None:
        report = run_sec_signal_ingestion(
            ["CRM", "ZZZZ"],
            submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
            cik_by_symbol={"CRM": "1108524"},
            lookback_days=90,
            as_of=date(2026, 3, 20),
        )
        self.assertEqual(report.failed_symbols, ("ZZZZ",))
        self.assertIsNone(report.results[0].error)
        self.assertGreaterEqual(report.event_writes, 1)
        self.assertTrue(report.results[1].error)


class SecSignalContextAndFirewallTests(unittest.TestCase):
    def test_signal_context_and_si_scores_unchanged(self) -> None:
        repo, _ = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20))
        service = SignalIntelligenceService(repo)
        facts = SecurityFacts(symbol="CRM", roic=18, roe=20, operating_margin=18, pe=30)
        participation = SecurityParticipationContext(status="Uygun", research_allowed=True)
        before = evaluate_security_intelligence(facts, participation)
        after = service.attach_to_view(before)
        context = after.signal_context
        self.assertGreaterEqual(len(context.recent_signals), 1)
        self.assertEqual(len(context.material_signals), 0)
        self.assertEqual(after.overall_score, before.overall_score)
        self.assertEqual(after.quality.score, before.quality.score)
        self.assertEqual(after.growth.score, before.growth.score)
        self.assertEqual(after.profitability.score, before.profitability.score)
        self.assertEqual(after.balance_sheet.score, before.balance_sheet.score)
        self.assertEqual(after.valuation.score, before.valuation.score)
        self.assertEqual(after.momentum.score, before.momentum.score)
        self.assertEqual(after.risk.score, before.risk.score)
        self.assertEqual(after.data_quality.score, before.data_quality.score)

    def test_participation_firewall_holds(self) -> None:
        view = evaluate_security_intelligence(
            SecurityFacts(symbol="AAPL", roic=18, roe=20, operating_margin=18, pe=30),
            SecurityParticipationContext(
                status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                research_allowed=False,
            ),
        )
        service = SignalIntelligenceService(InMemorySignalIntelligenceRepository())
        service.ingest(fixture_material_positive())
        attached = service.attach_to_view(view)
        self.assertFalse(attached.investable)
        self.assertEqual(attached.investment_state, "AVOID")
        self.assertEqual(attached.overall_score, view.overall_score)


class SecProviderSafetyTests(unittest.TestCase):
    def test_no_non_sec_provider_dependency(self) -> None:
        banned = ("fmp_client", "stock_news", "openai", "reddit", "twitter", "kap.org")
        for path in (ENGINE, INGEST, DISCOVERY, ADAPTERS, TAXONOMY, RUNNER):
            source = path.read_text(encoding="utf-8")
            lowered = source.lower()
            for token in banned:
                self.assertNotIn(token, lowered)
            self.assertNotIn("from services.fmp_client", source)
            self.assertNotIn("FMPClient", source)

    def test_runner_documents_lookback_and_hook(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("run_daily_scan", source)
        self.assertIn("Schedule is not activated", source)
        ingest = INGEST.read_text(encoding="utf-8")
        self.assertIn("no last-run cursor", ingest)


class PostgresTimestampReplayTests(unittest.TestCase):
    def test_timestamptz_roundtrip_does_not_rewrite(self) -> None:
        class TimestamptzRepo(InMemorySignalIntelligenceRepository):
            @staticmethod
            def _pg(value):
                text = str(value or "")
                return text.replace(".000Z", "+00:00").replace("Z", "+00:00") if text else value

            def get_event(self, event_id: str):
                row = super().get_event(event_id)
                if not row:
                    return None
                for key in ("event_time", "effective_time", "as_of"):
                    row[key] = self._pg(row.get(key))
                return row

            def get_evidence(self, evidence_id: str):
                row = super().get_evidence(evidence_id)
                if not row:
                    return None
                row["as_of"] = self._pg(row.get("as_of"))
                return row

        repo, first = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20), repo=TimestamptzRepo())
        self.assertEqual(first.event_writes, 1)
        _, replay = _ingest(fixture_crm_single_item_8k(), as_of=date(2026, 3, 20), repo=repo)
        self.assertEqual(replay.event_writes, 0)
        self.assertEqual(replay.evidence_writes, 0)


class SecHeadlineMustNotCreateItems(unittest.TestCase):
    def test_headline_text_is_not_item_evidence(self) -> None:
        payload = submissions_from_rows(
            [
                {
                    "accessionNumber": "0001108524-26-000400",
                    "filingDate": "2026-06-01",
                    "acceptanceDateTime": "2026-06-01T12:00:00.000Z",
                    "primaryDocument": "crm-8k.htm",
                    "form": "8-K",
                    "items": "Material Definitive Agreement",
                }
            ]
        )
        filings = discover_recent_8k_filings(
            payload,
            symbol="CRM",
            cik="1108524",
            lookback_days=30,
            as_of=date(2026, 6, 2),
        )
        raws = raw_inputs_from_8k_filing(filings[0])
        self.assertEqual(len(raws), 1)
        self.assertIsNone(raws[0].logical_event_key)
        self.assertNotEqual(raws[0].event_type, "MAJOR_CONTRACT")


if __name__ == "__main__":
    unittest.main()
