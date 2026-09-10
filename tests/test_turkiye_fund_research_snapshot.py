from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

from services.fund_product_contract import IDENTITY_RESOLVED
from services.turkiye_fund_broad_capture import (
    EVIDENCE_RECOVERY_VERSION,
    _pack_is_reusable,
)

SCRIPT = Path("scripts/run_turkiye_fund_research_snapshot.py")
spec = importlib.util.spec_from_file_location("fund14a_runner", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class DummyIdentity:
    def __init__(self, code, index):
        self.fund_code = code
        self.kap_disclosure_index = index


class Fund14AResearchSnapshotTests(unittest.TestCase):
    def test_business_day_shard_does_not_skip_weekend(self):
        friday = date(2026, 9, 4)
        monday = date(2026, 9, 7)
        self.assertEqual(
            mod.business_day_index(monday) - mod.business_day_index(friday),
            1,
        )

    def test_five_shards_are_disjoint_and_cover(self):
        codes = list("ABCDEFGHIJKLM")
        groups = [
            set(mod.select_shard(codes, shard_count=5, shard_index=i))
            for i in range(5)
        ]
        self.assertEqual(set.union(*groups), set(codes))
        for i in range(5):
            for j in range(i + 1, 5):
                self.assertFalse(groups[i] & groups[j])

    def test_broad_capture_keeps_rolling_shard_and_adds_active_protected_codes(self):
        active = [f"F{i:03d}" for i in range(20)]
        rolling = set(
            mod.select_shard(
                active,
                shard_count=5,
                shard_index=2,
            )
        )
        protected = next(code for code in active if code not in rolling)

        selected = set(
            mod.select_broad_capture_codes(
                active,
                shard_count=5,
                shard_index=2,
                protected_codes={protected, "NOT_ACTIVE"},
            )
        )

        self.assertTrue(rolling.issubset(selected))
        self.assertIn(protected, selected)
        self.assertNotIn("NOT_ACTIVE", selected)

    def test_protected_pack_requires_participation_evidence_before_reuse(self):
        identity = DummyIdentity("KCL", 123)

        complete = {
            "fund_code": "KCL",
            "evidence_recovery_version": EVIDENCE_RECOVERY_VERSION,
            "production_persist": False,
            "identity_status": IDENTITY_RESOLVED,
            "kap_disclosure_index": 123,
            "documents": {
                "BILGI_FORMU": {
                    "file_oid": "official-ybf-oid",
                },
            },
            "mandate_excerpts": [
                "Fon katılım fonu statüsündedir.",
            ],
            "governance_excerpts": [
                "Danışma Komitesi tarafından icazet verilmiştir.",
            ],
            "review_reasons": [],
        }

        self.assertTrue(
            _pack_is_reusable(
                complete,
                identity,
                require_participation_evidence=True,
            )
        )

        degraded = {
            **complete,
            "mandate_excerpts": [],
            "governance_excerpts": [],
            "review_reasons": [
                "YBF_MISSING",
                "TEXT_LAYER_UNAVAILABLE",
                "GOVERNANCE_EVIDENCE_MISSING",
            ],
        }

        # Ordinary incremental reuse remains backward compatible.
        self.assertTrue(
            _pack_is_reusable(
                degraded,
                identity,
            )
        )

        # Protected FUND14A activation evidence must be recaptured.
        self.assertFalse(
            _pack_is_reusable(
                degraded,
                identity,
                require_participation_evidence=True,
            )
        )

        weak = {
            **complete,
            "mandate_excerpts": [
                "Fonun yatırım stratejisi çeşitli sermaye piyasası araçlarını kapsar.",
            ],
            "governance_excerpts": [
                "Fon yönetiminde iç kontrol ve gözetim mekanizmaları uygulanır.",
            ],
        }
        # Non-empty excerpts are insufficient for protected activation reuse
        # unless they still contain accepted Participation methodology tokens.
        self.assertFalse(
            _pack_is_reusable(
                weak,
                identity,
                require_participation_evidence=True,
            )
        )

    def test_fund14a_wires_protected_codes_into_strict_pack_reuse(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            "require_participation_evidence_codes=protected_capture_codes",
            source,
        )

    def test_kap_windows_are_iso_and_split_year(self):
        self.assertEqual(
            mod.kap_windows(date(2027, 1, 10), 20),
            (
                ("2026-12-22", "2026-12-31"),
                ("2027-01-01", "2027-01-10"),
            ),
        )

    def test_catalog_merge_dedupes_disclosure_index(self):
        old = [
            {
                "fundCode": "AAA",
                "year": 2026,
                "period": 7,
                "disclosureIndex": 10,
                "x": 1,
            }
        ]
        new = [
            {
                "fundCode": "AAA",
                "year": 2026,
                "period": 7,
                "disclosureIndex": 10,
                "x": 2,
            },
            {
                "fundCode": "AAA",
                "year": 2026,
                "period": 8,
                "disclosureIndex": 11,
                "x": 3,
            },
        ]
        merged = mod.merge_catalog_rows(old, new)
        self.assertEqual(len(merged), 2)
        self.assertEqual(
            next(row for row in merged if row["disclosureIndex"] == 10)["x"],
            2,
        )

    def test_tefas_overlay_refresh_wins_without_erasing_old(self):
        old = {
            "AAA": {
                "observed_at": "2026-09-01T00:00:00+00:00",
                "snapshot": {"fonKodu": "AAA", "sonFiyat": 1},
            },
            "BBB": {
                "observed_at": "2026-09-01T00:00:00+00:00",
                "snapshot": {"fonKodu": "BBB", "sonFiyat": 2},
            },
        }
        updated = mod.update_tefas_overlay(
            old,
            {"AAA": {"fonKodu": "AAA", "sonFiyat": 3}},
            observed_at="2026-09-06T00:00:00+00:00",
        )
        self.assertEqual(updated["AAA"]["snapshot"]["sonFiyat"], 3)
        self.assertEqual(updated["BBB"]["snapshot"]["sonFiyat"], 2)

    def test_stale_kap_pack_is_quarantined(self):
        packs = {
            "AAA": {"fund_code": "AAA", "kap_disclosure_index": 10},
            "BBB": {"fund_code": "BBB", "kap_disclosure_index": 20},
            "AIS": {"fund_code": "AIS", "pilot_frozen": True},
        }
        identities = [
            DummyIdentity("AAA", 11),
            DummyIdentity("BBB", 20),
            DummyIdentity("AIS", 99),
        ]
        current, quarantined = mod.filter_current_packs(packs, identities)
        self.assertEqual(quarantined, ("AAA",))
        self.assertNotIn("AAA", current)
        self.assertIn("BBB", current)
        self.assertIn("AIS", current)

    def test_overlay_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            tefas = root / "tefas.json"

            rows = [{"fundCode": "AAA", "disclosureIndex": 1}]
            mod.save_catalog_overlay(
                catalog,
                rows,
                observed_at="2026-09-06T00:00:00+00:00",
            )
            self.assertEqual(mod.load_catalog_overlay(catalog), rows)

            overlay = {
                "AAA": {
                    "observed_at": "2026-09-06T00:00:00+00:00",
                    "snapshot": {"fonKodu": "AAA"},
                }
            }
            mod.save_tefas_overlay(tefas, overlay)
            self.assertEqual(mod.load_tefas_overlay(tefas), overlay)

    def test_tefas_discovery_sweeps_all_kap_codes_and_new_codes_immediately(self):
        codes = [f"F{i:03d}" for i in range(30)]
        selected = mod.tefas_discovery_refresh_codes(
            codes,
            ["NEW"],
            shard_count=10,
            shard_index=3,
            excluded_codes={"F003"},
        )
        self.assertIn("NEW", selected)
        self.assertNotIn("F003", selected)
        expected = set(
            mod.select_shard(codes, shard_count=10, shard_index=3)
        ) - {"F003"}
        self.assertEqual(set(selected) - {"NEW"}, expected)

    def test_pack_tefas_refresh_updates_history_and_clears_history_missing(self):
        pack = {
            "fund_code": "AAA",
            "review_reasons": ["HISTORY_INSUFFICIENT"],
        }
        updated = mod.update_pack_with_tefas_refresh(
            pack,
            snapshot={"fonKodu": "AAA", "tefas_present": True},
            history={
                "available": True,
                "rows": [{"fonKodu": "AAA", "tarih": "2026-09-07", "fiyat": 1.2}],
                "row_count": 1,
                "periyod": 12,
                "latest_date": "2026-09-07",
            },
            observed_at="2026-09-07T17:30:00+00:00",
        )
        self.assertNotIn("HISTORY_INSUFFICIENT", updated["review_reasons"])
        self.assertEqual(len(updated["tefas_price_rows"]), 1)
        self.assertTrue(updated["tefas_refresh"]["history_ok"])

    def test_pack_tefas_refresh_failure_marks_fail_closed(self):
        updated = mod.update_pack_with_tefas_refresh(
            {"fund_code": "AAA", "review_reasons": []},
            snapshot=None,
            history={"available": False, "rows": []},
            observed_at="2026-09-07T17:30:00+00:00",
        )
        self.assertIn("SOURCE_STALE", updated["review_reasons"])
        self.assertIn("HISTORY_INSUFFICIENT", updated["review_reasons"])

    def test_pilot_frozen_pack_is_not_mutated(self):
        pack = {
            "fund_code": "AIS",
            "pilot_frozen": True,
            "review_reasons": [],
        }
        updated = mod.update_pack_with_tefas_refresh(
            pack,
            snapshot={"fonKodu": "AIS", "tefas_present": False},
            history={"available": False, "rows": []},
            observed_at="2026-09-07T17:30:00+00:00",
        )
        self.assertEqual(updated, pack)

    def test_tefas_owned_source_stale_clears_after_success(self):
        pack = {
            "fund_code": "AAA",
            "review_reasons": ["SOURCE_STALE"],
            "tefas_refresh": {
                "snapshot_ok": False,
                "history_ok": True,
            },
        }
        updated = mod.update_pack_with_tefas_refresh(
            pack,
            snapshot={"fonKodu": "AAA", "tefas_present": True},
            history={
                "available": True,
                "rows": [{"fonKodu": "AAA", "tarih": "2026-09-07", "fiyat": 1.2}],
                "row_count": 1,
                "periyod": 12,
                "latest_date": "2026-09-07",
            },
            observed_at="2026-09-07T17:30:00+00:00",
        )
        self.assertNotIn("SOURCE_STALE", updated["review_reasons"])

    def test_unowned_source_stale_is_preserved(self):
        pack = {
            "fund_code": "AAA",
            "review_reasons": ["SOURCE_STALE"],
        }
        updated = mod.update_pack_with_tefas_refresh(
            pack,
            snapshot={"fonKodu": "AAA", "tefas_present": True},
            history={
                "available": True,
                "rows": [{"fonKodu": "AAA", "tarih": "2026-09-07", "fiyat": 1.2}],
                "row_count": 1,
                "periyod": 12,
                "latest_date": "2026-09-07",
            },
            observed_at="2026-09-07T17:30:00+00:00",
        )
        self.assertIn("SOURCE_STALE", updated["review_reasons"])


if __name__ == "__main__":
    unittest.main()
