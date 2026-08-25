from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repositories.sec_filing_evidence_cache import SecFilingEvidenceCache
from services.sec_filing_evidence import (
    SOURCE_SEC_PRIMARY_FILING,
    SecFilingEvidenceCacheError,
    digest_raw_bytes,
)
from services.sec_primary_filing_resolver import resolve_annual_filing_for_period
from tests.test_participation_inline_xbrl_attribution import CRM_MINIMAL_IXBRL


class FilingDigestAndCacheTests(unittest.TestCase):
    def test_store_hit_miss_and_immutable_duplicate(self) -> None:
        raw = CRM_MINIMAL_IXBRL.encode("utf-8")
        with TemporaryDirectory() as tmp:
            cache = SecFilingEvidenceCache(root=Path(tmp))
            first, created = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001108524-26-000001",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="crm.htm",
                raw_bytes=raw,
                fiscal_year=2026,
            )
            self.assertTrue(created)
            self.assertEqual(first.source, SOURCE_SEC_PRIMARY_FILING)
            cache.verify_digest(first.content_digest)
            second, created_again = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001108524-26-000001",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="crm.htm",
                raw_bytes=raw,
            )
            self.assertFalse(created_again)
            self.assertEqual(first.content_digest, second.content_digest)
            self.assertEqual(len(list((Path(tmp) / "objects").glob("*.bin"))), 1)

    def test_changed_bytes_create_new_digest(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecFilingEvidenceCache(root=Path(tmp))
            first, _ = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="a.htm",
                raw_bytes=b"<html>one</html>",
            )
            second, created = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="a.htm",
                raw_bytes=b"<html>two</html>",
            )
            self.assertTrue(created)
            self.assertNotEqual(first.content_digest, second.content_digest)
            self.assertTrue(cache.get_by_digest(first.content_digest))

    def test_corrupt_bytes_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecFilingEvidenceCache(root=Path(tmp))
            evidence, _ = cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="0001",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="a.htm",
                raw_bytes=b"<html>ok</html>",
            )
            path = Path(tmp) / "objects" / f"{evidence.content_digest}.bin"
            path.write_bytes(b"<html>tampered</html>")
            with self.assertRaises(SecFilingEvidenceCacheError):
                cache.get_by_digest(evidence.content_digest)

    def test_digest_is_raw_bytes_identity(self) -> None:
        self.assertEqual(digest_raw_bytes(b"abc"), digest_raw_bytes(b"abc"))
        self.assertNotEqual(digest_raw_bytes(b"abc"), digest_raw_bytes(b"abd"))

    def test_accession_latest_lookup(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecFilingEvidenceCache(root=Path(tmp))
            cache.store_if_new(
                symbol="CRM",
                cik="1108524",
                accession="ACC-1",
                form="10-K",
                filing_date="2026-03-01",
                primary_document="a.htm",
                raw_bytes=b"<html>acc</html>",
            )
            loaded = cache.get_latest(accession="ACC-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.accession, "ACC-1")


class PeriodAlignedFilingResolverTests(unittest.TestCase):
    def test_prefers_matching_report_date(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-K"],
                    "accessionNumber": ["0001-24-000001", "0001-25-000010"],
                    "filingDate": ["2025-02-01", "2026-02-01"],
                    "reportDate": ["2024-12-31", "2025-12-31"],
                    "primaryDocument": ["old.htm", "new.htm"],
                }
            }
        }
        selected = resolve_annual_filing_for_period(
            submissions,
            cik="320193",
            preferred_period_end="2025-12-31",
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.accession_number, "0001-25-000010")
        self.assertEqual(selected.primary_document, "new.htm")

    def test_prefers_matching_accession(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-K"],
                    "accessionNumber": ["AAA", "BBB"],
                    "filingDate": ["2026-03-01", "2026-02-01"],
                    "reportDate": ["2025-12-31", "2025-12-31"],
                    "primaryDocument": ["a.htm", "b.htm"],
                }
            }
        }
        selected = resolve_annual_filing_for_period(
            submissions,
            cik="1",
            preferred_accession="BBB",
        )
        self.assertEqual(selected.accession_number, "BBB")

    def test_accepts_20f_for_period_alignment(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["20-F"],
                    "accessionNumber": ["0001-25-000020"],
                    "filingDate": ["2026-03-01"],
                    "reportDate": ["2025-12-31"],
                    "primaryDocument": ["f20.htm"],
                }
            }
        }
        selected = resolve_annual_filing_for_period(
            submissions,
            cik="1",
            preferred_period_end="2025-12-31",
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.form, "20-F")


if __name__ == "__main__":
    unittest.main()
