import unittest
from unittest.mock import MagicMock

from repositories.candidate_repository import CandidateRepository
from services.candidate_persistence import (
    CANONICAL_PERSISTED_COLUMNS,
    NON_PERSISTED_CANDIDATE_FIELDS,
    OPTIONAL_SCHEMA_FALLBACK_FIELDS,
    PERSISTED_CANDIDATE_COLUMNS,
    dropped_candidate_fields,
    execute_with_schema_fallback,
    prepare_candidate_payload,
)

OPTIONAL_METADATA_FIELDS = (
    "financial_currency",
    "financial_taxonomy",
    "pe_source",
    "freshness_status",
    "freshness_label",
    "period_age_days",
    "freshness_score",
)


class CandidatePersistenceTests(unittest.TestCase):
    def _sample_payload(self):
        return {
            "symbol": "TEST",
            "market": "ABD",
            "company_name": "Test Co",
            "financial_currency": "TWD",
            "financial_taxonomy": "ifrs-full",
            "pe_source": "quote",
            "freshness_status": "FRESH",
            "freshness_label": "Güncel finansal dönem",
            "period_age_days": 120,
            "freshness_score": 100.0,
            "fmp_source_status": {
                "fmp_profile": "OK",
                "fmp_quote": "RATE_LIMIT",
            },
            "future_unknown_field": "should_drop",
        }

    def test_transient_metadata_is_not_persisted(self) -> None:
        cleaned = prepare_candidate_payload(self._sample_payload())
        self.assertNotIn("fmp_source_status", cleaned)
        self.assertIn("financial_currency", cleaned)
        self.assertIn("pe_source", cleaned)

    def test_all_optional_metadata_fields_preserved(self) -> None:
        cleaned = prepare_candidate_payload(self._sample_payload())
        for field in OPTIONAL_METADATA_FIELDS:
            self.assertIn(field, cleaned)

    def test_unknown_fields_are_filtered(self) -> None:
        cleaned = prepare_candidate_payload(self._sample_payload())
        self.assertNotIn("future_unknown_field", cleaned)
        dropped = dropped_candidate_fields(self._sample_payload())
        self.assertEqual(dropped["future_unknown_field"], "unknown_column")
        self.assertEqual(dropped["fmp_source_status"], "scan_snapshot_only")

    def test_existing_core_fields_regression(self) -> None:
        payload = {
            "symbol": "AAPL",
            "market": "ABD",
            "nabi_score": 71.4,
            "decision_label": "İZLE",
            "research_confidence": 80.0,
            "conviction_score": 65.0,
            "opportunity_score": 55.0,
            "score_confidence": "YÜKSEK",
        }
        cleaned = prepare_candidate_payload(payload)
        self.assertEqual(cleaned, payload)

    def test_non_persisted_fields_constant(self) -> None:
        self.assertIn("fmp_source_status", NON_PERSISTED_CANDIDATE_FIELDS)

    def test_optional_fallback_fields_are_subset_of_persisted(self) -> None:
        self.assertTrue(OPTIONAL_SCHEMA_FALLBACK_FIELDS <= PERSISTED_CANDIDATE_COLUMNS)
        self.assertEqual(len(OPTIONAL_SCHEMA_FALLBACK_FIELDS), 7)

    def test_canonical_fields_exclude_optional_metadata(self) -> None:
        for field in OPTIONAL_METADATA_FIELDS:
            self.assertNotIn(field, CANONICAL_PERSISTED_COLUMNS)
        for field in ("symbol", "market", "nabi_score", "decision_label"):
            self.assertIn(field, CANONICAL_PERSISTED_COLUMNS)

    def test_optional_metadata_missing_column_strips_and_retries(self) -> None:
        attempts = []

        def writer(payload):
            attempts.append(dict(payload))
            if "financial_currency" in payload:
                raise RuntimeError(
                    "Could not find the 'financial_currency' column "
                    "of 'investment_candidates' in the schema cache"
                )
            return payload

        result = execute_with_schema_fallback(
            {
                "symbol": "TEST",
                "market": "ABD",
                "financial_currency": "USD",
                "nabi_score": 70.0,
            },
            writer,
        )
        self.assertEqual(result["symbol"], "TEST")
        self.assertNotIn("financial_currency", attempts[-1])
        self.assertEqual(len(attempts), 2)

    def test_canonical_missing_column_fails_loudly(self) -> None:
        def writer(_payload):
            raise RuntimeError(
                "Could not find the 'nabi_score' column "
                "of 'investment_candidates' in the schema cache"
            )

        with self.assertRaises(RuntimeError) as ctx:
            execute_with_schema_fallback(
                {
                    "symbol": "TEST",
                    "market": "ABD",
                    "nabi_score": 70.0,
                },
                writer,
            )
        self.assertIn("nabi_score", str(ctx.exception))


class CandidateRepositoryPersistenceTests(unittest.TestCase):
    def _repo_with_table(self):
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        return CandidateRepository(client), table

    def test_upsert_uses_sanitized_payload(self) -> None:
        repo, table = self._repo_with_table()
        upsert_query = MagicMock()
        table.upsert.return_value = upsert_query
        upsert_query.execute.return_value = MagicMock(data=[{"symbol": "TEST"}])

        repo.upsert_by_symbol({
            "symbol": "TEST",
            "market": "ABD",
            "financial_currency": "USD",
            "fmp_source_status": {"fmp_quote": "OK"},
            "unexpected_field": True,
        })

        payload = table.upsert.call_args.args[0]
        self.assertIn("financial_currency", payload)
        self.assertNotIn("fmp_source_status", payload)
        self.assertNotIn("unexpected_field", payload)

    def test_create_uses_sanitized_payload(self) -> None:
        repo, table = self._repo_with_table()
        insert_query = MagicMock()
        table.insert.return_value = insert_query
        insert_query.execute.return_value = MagicMock(data=[{"symbol": "TEST"}])

        repo.create({
            "symbol": "TEST",
            "market": "ABD",
            "pe_source": "quote",
            "fmp_source_status": {"fmp_quote": "OK"},
            "unexpected_field": True,
        })

        payload = table.insert.call_args.args[0]
        self.assertIn("pe_source", payload)
        self.assertNotIn("fmp_source_status", payload)
        self.assertNotIn("unexpected_field", payload)

    def test_update_uses_sanitized_payload(self) -> None:
        repo, table = self._repo_with_table()
        update_query = MagicMock()
        table.update.return_value = update_query
        update_query.eq.return_value = update_query
        update_query.execute.return_value = MagicMock(data=[{"symbol": "TEST"}])

        repo.update(
            "candidate-id",
            {
                "freshness_status": "STALE",
                "fmp_source_status": {"fmp_quote": "OK"},
                "unexpected_field": True,
            },
        )

        payload = table.update.call_args.args[0]
        self.assertIn("freshness_status", payload)
        self.assertNotIn("fmp_source_status", payload)
        self.assertNotIn("unexpected_field", payload)

    def test_upsert_canonical_schema_drift_raises(self) -> None:
        repo, table = self._repo_with_table()
        upsert_query = MagicMock()
        table.upsert.return_value = upsert_query
        upsert_query.execute.side_effect = RuntimeError(
            "Could not find the 'decision_label' column "
            "of 'investment_candidates' in the schema cache"
        )

        with self.assertRaises(RuntimeError):
            repo.upsert_by_symbol({
                "symbol": "TEST",
                "market": "ABD",
                "decision_label": "İZLE",
            })


if __name__ == "__main__":
    unittest.main()
