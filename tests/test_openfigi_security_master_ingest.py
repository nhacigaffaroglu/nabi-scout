from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.official_fund_holdings_client import OfficialHolding
from services.openfigi_client import (
    ID_CUSIP,
    ID_SEDOL,
    MATCH_EXACT_SINGLE,
    MATCH_MULTIPLE,
    MATCH_NONE,
    OpenFigiCandidate,
    OpenFigiJob,
    OpenFigiJobResult,
    parse_mapping_entry,
)
from services.openfigi_security_master_ingest import (
    ACTION_CONFLICT,
    ACTION_INSERT,
    ACTION_NOOP,
    ACTION_SKIP,
    OPENFIGI_SOURCE_REFERENCE,
    WRITE_GATE_FAIL,
    WRITE_GATE_PASS,
    canonical_openfigi_instrument,
    fact_from_qualification,
    ingest_openfigi_facts,
    jobs_from_official_holdings,
    plan_openfigi_ingest,
    whitelist_supports_fixed_income,
)
from services.openfigi_evidence_qualification import qualify_mapping
from services.security_master_contract import (
    IDENTIFIER_TYPE_SEDOL,
    INSTRUMENT_EQUITY,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_SUKUK,
    SOURCE_PROVIDER_EXPLICIT,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_listing_ingest import SecurityMasterWriteGuard, SecurityMasterWriteGuardError
from services.security_master_service import SecurityMasterService, summarize_holding_coverage
from services.sukuk_evidence_contract import classify_from_name_or_fund

INGEST = Path("services/openfigi_security_master_ingest.py")
QUAL = Path("services/openfigi_evidence_qualification.py")
HYBRID = Path("services/hybrid_exposure_allocation_policy.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
LOOKTHROUGH = Path("services/portfolio_economic_exposure.py")


def _candidate(**kwargs) -> OpenFigiCandidate:
    defaults = dict(
        figi="BBG000000001",
        name="KSA Sukuk Ltd",
        ticker="EX1",
        exch_code="US",
        security_type="EURO-DOLLAR",
        security_type2="Govt",
        market_sector="Govt",
        composite_figi="BBG000000002",
        share_class_figi="",
    )
    defaults.update(kwargs)
    return OpenFigiCandidate(**defaults)


def _job(id_type=ID_SEDOL, id_value="BT6MTT4") -> OpenFigiJob:
    return OpenFigiJob(id_type=id_type, id_value=id_value)


def _result(candidate=None, *, status=MATCH_EXACT_SINGLE, job=None) -> OpenFigiJobResult:
    chosen = candidate or _candidate()
    return OpenFigiJobResult(
        job=job or _job(),
        match_status=status,
        http_status=200,
        candidates=(chosen,) if status == MATCH_EXACT_SINGLE else (),
    )


def _holding(**kwargs) -> OfficialHolding:
    defaults = dict(
        fund_symbol="SPSK",
        as_of=date(2026, 8, 28),
        ticker="BT6MTT4",
        cusip_raw="BT6MTT4",
        security_name="KSA Sukuk Ltd",
        weight_pct=1.25,
    )
    defaults.update(kwargs)
    return OfficialHolding(**defaults)


def _us_listing(identifier: str, instrument_type: str) -> SecurityFact:
    return SecurityFact(
        identifier=identifier,
        identifier_type=IDENTIFIER_TYPE_SEDOL,
        instrument_type=instrument_type,
        source=SOURCE_US_LISTING,
        observed_at="2026-01-01T00:00:00+00:00",
    )


class QualificationPersistenceTests(unittest.TestCase):
    def test_whitelist_only_and_not_broadened(self) -> None:
        self.assertTrue(whitelist_supports_fixed_income("EURO-DOLLAR", "Govt"))
        self.assertTrue(whitelist_supports_fixed_income("EURO MTN", "Corp"))
        self.assertFalse(whitelist_supports_fixed_income("PRIV PLACEMENT", ""))
        self.assertFalse(whitelist_supports_fixed_income("Weird Debt Like", ""))
        from services.openfigi_evidence_qualification import OPENFIGI_FIXED_INCOME_EXACT

        self.assertIn("EURO-DOLLAR", OPENFIGI_FIXED_INCOME_EXACT)
        self.assertIn("EURO MTN", OPENFIGI_FIXED_INCOME_EXACT)
        self.assertNotIn("ASSET BACKED SECURITY", OPENFIGI_FIXED_INCOME_EXACT)
        self.assertNotIn("PREFERRED", OPENFIGI_FIXED_INCOME_EXACT)

    def test_name_sukuk_does_not_create_sukuk_fact(self) -> None:
        self.assertEqual(classify_from_name_or_fund("KSA Sukuk Ltd", "SPSK"), "UNKNOWN")
        row = parse_mapping_entry(
            {"data": [_candidate(name="KSA Sukuk Ltd").to_dict()]},
            job=_job(),
            http_status=200,
        )
        q = qualify_mapping(row, official_name="KSA Sukuk Ltd")
        self.assertEqual(canonical_openfigi_instrument(q), INSTRUMENT_FIXED_INCOME)
        fact = fact_from_qualification(_job(), q, observed_at="2026-08-29T00:00:00+00:00")
        self.assertIsNotNone(fact)
        assert fact is not None
        self.assertEqual(fact.instrument_type, INSTRUMENT_FIXED_INCOME)
        self.assertNotEqual(fact.instrument_type, INSTRUMENT_SUKUK)
        self.assertNotIn("Sukuk", str(fact.metadata))
        self.assertIsNone(fact.issuer_name)

    def test_explicit_sukuk_type_is_not_persisted(self) -> None:
        row = parse_mapping_entry(
            {"data": [_candidate(security_type="Sukuk", security_type2="").to_dict()]},
            job=_job(),
            http_status=200,
        )
        q = qualify_mapping(row)
        self.assertEqual(q.instrument_type, INSTRUMENT_SUKUK)
        self.assertEqual(canonical_openfigi_instrument(q), "")
        self.assertIsNone(fact_from_qualification(_job(), q))

    def test_bond_persists_as_fixed_income_not_sukuk(self) -> None:
        row = parse_mapping_entry(
            {"data": [_candidate(security_type="Bond", security_type2="Corp").to_dict()]},
            job=_job(),
            http_status=200,
        )
        fact = fact_from_qualification(_job(), qualify_mapping(row))
        self.assertEqual(fact.instrument_type, INSTRUMENT_FIXED_INCOME)
        self.assertEqual(fact.source, SOURCE_PROVIDER_EXPLICIT)
        self.assertEqual(fact.source_reference, OPENFIGI_SOURCE_REFERENCE)
        self.assertEqual(fact.metadata["figi"], "BBG000000001")
        self.assertEqual(fact.metadata["compositeFIGI"], "BBG000000002")


class PlanAndGateTests(unittest.TestCase):
    def test_unmapped_and_cash_remain_unknown(self) -> None:
        jobs = jobs_from_official_holdings(
            (
                _holding(),
                _holding(ticker="Cash&Other", cusip_raw="Cash&Other", security_name="Cash&Other", weight_pct=2.07),
                _holding(ticker="Y57542AA3", cusip_raw="Y57542AA3", weight_pct=0.52),
            )
        )
        symbols = {job.id_value for job, _name, _w in jobs}
        self.assertIn("BT6MTT4", symbols)
        self.assertNotIn("Cash&Other", symbols)
        self.assertIn("Y57542AA3", symbols)
        none = OpenFigiJobResult(
            job=_job(ID_CUSIP, "Y57542AA3"),
            match_status=MATCH_NONE,
            http_status=200,
            warning="No identifier found.",
        )
        plan = plan_openfigi_ingest(((none.job, none, 0.52),), existing_rows=())
        self.assertEqual(plan.skipped, 1)
        self.assertEqual(plan.inserts, 0)
        self.assertEqual(plan.sukuk_planned, 0)

    def test_multiple_matches_fail_closed(self) -> None:
        job = _job()
        result = OpenFigiJobResult(
            job=job,
            match_status=MATCH_MULTIPLE,
            http_status=200,
            candidates=(
                _candidate(figi="A", name="ONE"),
                _candidate(figi="B", name="TWO"),
            ),
        )
        plan = plan_openfigi_ingest(((job, result, 1.0),))
        self.assertEqual(plan.multiple_matches, 1)
        self.assertEqual(plan.write_gate, WRITE_GATE_FAIL)
        self.assertIn("MULTIPLE_MATCHES", plan.write_gate_reasons)
        master = SecurityMasterService(include_canonical_static=False)
        written = ingest_openfigi_facts(master, plan)
        self.assertEqual(written.inserted, 0)
        self.assertEqual(master.repo.count(), 0)

    def test_higher_precedence_not_overwritten(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(_us_listing("BT6MTT4", INSTRUMENT_EQUITY))
        result = _result()
        plan = plan_openfigi_ingest(
            ((result.job, result, 1.25),),
            existing_rows=master.repo.list_all(),
        )
        self.assertEqual(plan.conflicts, 1)
        self.assertEqual(plan.rows[0].reason, "HIGHER_PRECEDENCE_CONFLICT")
        self.assertEqual(plan.write_gate, WRITE_GATE_FAIL)
        ingest_openfigi_facts(master, plan)
        self.assertEqual(master.resolve_security("BT6MTT4", identifier_type="SEDOL").instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(len(master.repo.list_all()), 1)

    def test_same_source_type_conflict_fail_closed(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                identifier="BT6MTT4",
                identifier_type=IDENTIFIER_TYPE_SEDOL,
                instrument_type=INSTRUMENT_EQUITY,
                source=SOURCE_PROVIDER_EXPLICIT,
                observed_at="2026-01-01T00:00:00+00:00",
                source_reference="holding.asset_type",
            )
        )
        result = _result()
        plan = plan_openfigi_ingest(
            ((result.job, result, 1.25),),
            existing_rows=master.repo.list_all(),
        )
        self.assertEqual(plan.rows[0].action, ACTION_CONFLICT)
        self.assertEqual(plan.write_gate, WRITE_GATE_FAIL)
        ingest_openfigi_facts(master, plan)
        self.assertEqual(master.resolve_security("BT6MTT4", identifier_type="SEDOL").instrument_type, INSTRUMENT_EQUITY)

    def test_idempotent_ingest_and_no_duplicate_row(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        result = _result()
        first_plan = plan_openfigi_ingest(
            ((result.job, result, 1.25),),
            existing_rows=(),
            observed_at="2026-08-29T00:00:00+00:00",
        )
        self.assertEqual(first_plan.write_gate, WRITE_GATE_PASS)
        self.assertEqual(first_plan.inserts, 1)
        first = ingest_openfigi_facts(master, first_plan)
        self.assertEqual(first.inserted, 1)
        replay_plan = plan_openfigi_ingest(
            ((result.job, result, 1.25),),
            existing_rows=master.repo.list_all(),
            observed_at="2026-08-30T00:00:00+00:00",
        )
        self.assertEqual(replay_plan.inserts, 0)
        self.assertEqual(replay_plan.updates, 0)
        self.assertEqual(replay_plan.noops, 1)
        second = ingest_openfigi_facts(master, replay_plan)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.updated, 0)
        self.assertEqual(len(master.repo.list_all()), 1)
        row = master.repo.list_all()[0]
        self.assertEqual(row["observed_at"], "2026-08-29T00:00:00+00:00")
        types = {item["instrument_type"] for item in master.repo.list_all()}
        self.assertNotIn(INSTRUMENT_SUKUK, types)


class LookthroughAndInvariantTests(unittest.TestCase):
    def test_lookthrough_reclassifies_fixed_income_not_sukuk(self) -> None:
        from services.fund_intelligence_contract import FundHoldingRow

        master = SecurityMasterService(include_canonical_static=False)
        result = _result()
        plan = plan_openfigi_ingest(((result.job, result, 96.78),), existing_rows=())
        ingest_openfigi_facts(master, plan)
        holdings = [
            FundHoldingRow("BT6MTT4", "KSA Sukuk Ltd", 96.78, None, None, None),
            FundHoldingRow("Cash&Other", "Cash&Other", 2.07, None, None, None),
            FundHoldingRow("Y57542AA3", "Malaysia Wakala Sukuk Bhd", 1.22, None, None, None),
        ]
        coverage = summarize_holding_coverage(holdings, security_master=master)
        self.assertEqual(coverage["classified_FIXED_INCOME"], 96.78)
        self.assertEqual(coverage["classified_SUKUK"], 0.0)
        self.assertEqual(coverage["UNKNOWN"], 3.29)

    def test_write_guard_and_no_official_snapshot_writes(self) -> None:
        class _Table:
            def upsert(self, *args, **kwargs):
                return {"ok": True}

        class _Client:
            def table(self, name):
                return _Table()

        guarded = SecurityMasterWriteGuard(_Client())
        guarded.table("security_master").upsert({"identifier": "BT6MTT4"})
        with self.assertRaises(SecurityMasterWriteGuardError):
            guarded.table("fund_holdings").upsert({"symbol": "SPSK"})
        with self.assertRaises(SecurityMasterWriteGuardError):
            guarded.table("fund_holdings_snapshots").insert({"symbol": "SPSK"})
        source = INGEST.read_text(encoding="utf-8")
        self.assertNotIn("fund_holdings", source)
        self.assertNotIn(".insert(", source)
        self.assertNotIn("enable_hybrid_exposure_allocation = True", source)
        self.assertIn("Never writes SUKUK", source)

    def test_hybrid_remains_off_and_strict_new_money_untouched(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        hybrid = HYBRID.read_text(encoding="utf-8")
        self.assertIn("enable_hybrid_exposure_allocation: bool = False", hybrid)
        new_money = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("enable_hybrid_exposure_allocation: Optional[bool] = None", new_money)
        self.assertNotIn("SPSK = SUKUK", INGEST.read_text())
        self.assertNotIn("SPSK = SUKUK", LOOKTHROUGH.read_text())


if __name__ == "__main__":
    unittest.main()
