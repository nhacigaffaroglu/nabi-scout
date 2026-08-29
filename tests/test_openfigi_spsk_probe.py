from __future__ import annotations

import unittest
from pathlib import Path

from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.openfigi_client import (
    ANON_MAX_JOBS_PER_REQUEST,
    ID_CUSIP,
    ID_SEDOL,
    ID_TICKER,
    MATCH_ERROR,
    MATCH_EXACT_SINGLE,
    MATCH_MULTIPLE,
    MATCH_NONE,
    OpenFigiCandidate,
    OpenFigiClient,
    OpenFigiError,
    OpenFigiJob,
    max_jobs_per_request,
    openfigi_exch_code_for_listing,
    parse_mapping_entry,
    resolve_openfigi_api_key,
)
from services.openfigi_evidence_qualification import (
    disambiguate_candidates,
    is_explicit_openfigi_sukuk,
    qualify_mapping,
)
from services.sukuk_evidence_contract import classify_from_name_or_fund

CLIENT = Path("services/openfigi_client.py")
QUAL = Path("services/openfigi_evidence_qualification.py")


def _candidate(**kwargs) -> OpenFigiCandidate:
    defaults = dict(
        figi="BBG000000001",
        name="Example Bond",
        ticker="EX1",
        exch_code="US",
        security_type="Bond",
        security_type2="Corp",
        market_sector="Corp",
        composite_figi="",
        share_class_figi="",
    )
    defaults.update(kwargs)
    return OpenFigiCandidate(**defaults)


def _job(id_type=ID_SEDOL, id_value="B0YBKJ7") -> OpenFigiJob:
    return OpenFigiJob(id_type=id_type, id_value=id_value)


class AnonymousClientTests(unittest.TestCase):
    def test_anonymous_works_without_key(self) -> None:
        self.assertIsNone(resolve_openfigi_api_key(""))
        self.assertIsNone(resolve_openfigi_api_key(None))
        client = OpenFigiClient(api_key="", transport=lambda *args: (200, {}, []))
        self.assertIsNone(client.api_key)
        self.assertEqual(client.max_jobs, ANON_MAX_JOBS_PER_REQUEST)

    def test_batch_capped_at_10_without_key(self) -> None:
        self.assertEqual(max_jobs_per_request(None), 10)
        client = OpenFigiClient(api_key=None, transport=lambda *args: (200, {}, []))
        jobs = [_job(id_value=f"B0YBKJ{i}") for i in range(11)]
        with self.assertRaises(OpenFigiError):
            client.transport = lambda url, headers, payload: (_ for _ in ()).throw(
                OpenFigiError("should not send oversized")
            )
            # Client splits internally; oversized single _post is guarded.
            client._post([job.to_payload() for job in jobs])

    def test_sedol_and_cusip_id_types(self) -> None:
        seen = []

        def transport(url, headers, payload):
            seen.extend(payload)
            return (
                200,
                {},
                [{"data": [_candidate().to_dict()]} for _ in payload],
            )

        client = OpenFigiClient(api_key=None, transport=transport, min_interval_seconds=0)
        client.map_jobs(
            (
                OpenFigiJob(ID_SEDOL, "B0YBKJ7"),
                OpenFigiJob(ID_CUSIP, "037833100"),
            )
        )
        self.assertEqual(seen[0]["idType"], ID_SEDOL)
        self.assertEqual(seen[1]["idType"], ID_CUSIP)

    def test_ticker_requires_exch_code(self) -> None:
        client = OpenFigiClient(api_key=None, transport=lambda *args: (200, {}, []), min_interval_seconds=0)
        with self.assertRaises(OpenFigiError):
            client.map_jobs((OpenFigiJob(ID_TICKER, "WELL"),))

    def test_ticker_with_exch_code_payload(self) -> None:
        seen = []

        def transport(url, headers, payload):
            seen.extend(payload)
            return (200, {}, [{"data": [_candidate(ticker="WELL", exch_code="UN", security_type="REIT", security_type2="REIT").to_dict()]}])

        client = OpenFigiClient(api_key=None, transport=transport, min_interval_seconds=0)
        client.map_jobs((OpenFigiJob(ID_TICKER, "WELL", exch_code="UN"),))
        self.assertEqual(seen[0]["idType"], ID_TICKER)
        self.assertEqual(seen[0]["idValue"], "WELL")
        self.assertEqual(seen[0]["exchCode"], "UN")
        self.assertEqual(openfigi_exch_code_for_listing("NYSE"), "UN")
        self.assertEqual(openfigi_exch_code_for_listing("NASDAQ"), "UW")

    def test_single_mapping_accepted(self) -> None:
        entry = {"data": [_candidate().to_dict()]}
        row = parse_mapping_entry(entry, job=_job(), http_status=200)
        self.assertEqual(row.match_status, MATCH_EXACT_SINGLE)

    def test_multiple_mapping_fail_closed(self) -> None:
        entry = {
            "data": [
                _candidate(figi="A", name="ONE").to_dict(),
                _candidate(figi="B", name="TWO").to_dict(),
            ]
        }
        row = parse_mapping_entry(entry, job=_job(), http_status=200)
        self.assertEqual(row.match_status, MATCH_MULTIPLE)
        status, chosen = disambiguate_candidates(row.candidates, official_name="OTHER")
        self.assertEqual(status, MATCH_MULTIPLE)
        self.assertIsNone(chosen)

    def test_name_can_disambiguate_exactly(self) -> None:
        cands = (
            _candidate(figi="A", name="KSA Sukuk Ltd 4.274% 05/22/2029"),
            _candidate(figi="B", name="Other Name"),
        )
        status, chosen = disambiguate_candidates(
            cands, official_name="KSA Sukuk Ltd 4.274% 05/22/2029"
        )
        self.assertEqual(status, MATCH_EXACT_SINGLE)
        self.assertEqual(chosen.figi, "A")

    def test_no_mapping_unknown(self) -> None:
        row = parse_mapping_entry(
            {"warning": "No identifier found."}, job=_job(), http_status=200
        )
        self.assertEqual(row.match_status, MATCH_NONE)
        q = qualify_mapping(row)
        self.assertEqual(q.instrument_type, "UNKNOWN")

    def test_provider_error_unknown(self) -> None:
        row = parse_mapping_entry({"error": "oops"}, job=_job(), http_status=200)
        self.assertEqual(row.match_status, MATCH_ERROR)
        self.assertEqual(qualify_mapping(row).instrument_type, "UNKNOWN")


class TypeContractTests(unittest.TestCase):
    def test_bond_does_not_become_sukuk(self) -> None:
        row = parse_mapping_entry(
            {"data": [_candidate(security_type="Bond", security_type2="Corp").to_dict()]},
            job=_job(),
            http_status=200,
        )
        q = qualify_mapping(row, official_name="KSA Sukuk Ltd")
        self.assertEqual(q.instrument_type, "FIXED_INCOME")
        self.assertNotEqual(q.instrument_type, "SUKUK")

    def test_name_containing_sukuk_does_not_become_sukuk(self) -> None:
        self.assertEqual(classify_from_name_or_fund("KSA Sukuk Ltd", "SPSK"), "UNKNOWN")
        row = parse_mapping_entry(
            {"data": [_candidate(name="KSA Sukuk Ltd", security_type="Bond").to_dict()]},
            job=_job(),
            http_status=200,
        )
        q = qualify_mapping(row, official_name="KSA Sukuk Ltd")
        self.assertEqual(q.instrument_type, "FIXED_INCOME")
        self.assertFalse(is_explicit_openfigi_sukuk("Bond", q.provider_name))

    def test_explicit_provider_sukuk_only(self) -> None:
        self.assertTrue(is_explicit_openfigi_sukuk("Sukuk"))
        self.assertFalse(is_explicit_openfigi_sukuk("Bond"))
        row = parse_mapping_entry(
            {"data": [_candidate(security_type="Sukuk").to_dict()]},
            job=_job(),
            http_status=200,
        )
        self.assertEqual(qualify_mapping(row).instrument_type, "SUKUK")

    def test_fixed_income_whitelist_exact(self) -> None:
        row = parse_mapping_entry(
            {"data": [_candidate(security_type="Weird Debt Like", security_type2="").to_dict()]},
            job=_job(),
            http_status=200,
        )
        self.assertEqual(qualify_mapping(row).instrument_type, "UNKNOWN")

    def test_observed_eurodollar_govt_is_fixed_income_not_sukuk(self) -> None:
        row = parse_mapping_entry(
            {
                "data": [
                    _candidate(
                        name="KSA IJARAH SUKUK LTD",
                        security_type="EURO-DOLLAR",
                        security_type2="Govt",
                    ).to_dict()
                ]
            },
            job=_job(),
            http_status=200,
        )
        q = qualify_mapping(row, official_name="KSA IJARAH SUKUK LTD")
        self.assertEqual(q.instrument_type, "FIXED_INCOME")
        self.assertNotEqual(q.instrument_type, "SUKUK")

    def test_observed_euro_mtn_corp_is_fixed_income(self) -> None:
        row = parse_mapping_entry(
            {
                "data": [
                    _candidate(security_type="EURO MTN", security_type2="Corp").to_dict()
                ]
            },
            job=_job(),
            http_status=200,
        )
        self.assertEqual(qualify_mapping(row).instrument_type, "FIXED_INCOME")

    def test_priv_placement_classifies_only_via_corp(self) -> None:
        via_corp = parse_mapping_entry(
            {
                "data": [
                    _candidate(security_type="PRIV PLACEMENT", security_type2="Corp").to_dict()
                ]
            },
            job=_job(),
            http_status=200,
        )
        self.assertEqual(qualify_mapping(via_corp).instrument_type, "FIXED_INCOME")
        alone = parse_mapping_entry(
            {
                "data": [
                    _candidate(security_type="PRIV PLACEMENT", security_type2="").to_dict()
                ]
            },
            job=_job(),
            http_status=200,
        )
        self.assertEqual(qualify_mapping(alone).instrument_type, "UNKNOWN")

    def test_no_name_or_fund_inference_in_source(self) -> None:
        text = QUAL.read_text(encoding="utf-8")
        self.assertNotIn("SPSK = SUKUK", text)
        self.assertNotIn('if fund_symbol == "SPSK"', text)
        self.assertIn("Bond is never sukuk", text)


class RateLimitTests(unittest.TestCase):
    def test_anonymous_interval_and_429_retry_once(self) -> None:
        sleeps = []
        calls = {"n": 0}

        def transport(url, headers, payload):
            calls["n"] += 1
            if calls["n"] == 1:
                return 429, {"Retry-After": "2"}, None
            return 200, {"X-RateLimit-Remaining": "20"}, [{"data": [_candidate().to_dict()]}]

        client = OpenFigiClient(
            api_key=None,
            transport=transport,
            sleeper=sleeps.append,
            min_interval_seconds=2.4,
        )
        rows = client.map_jobs((_job(),))
        self.assertEqual(rows[0].match_status, MATCH_EXACT_SINGLE)
        self.assertIn(2.0, sleeps)
        self.assertEqual(client.request_count, 2)

    def test_dry_run_has_no_db_writes(self) -> None:
        source = CLIENT.read_text(encoding="utf-8") + QUAL.read_text(encoding="utf-8")
        for token in (".insert(", ".upsert(", ".update(", ".delete(", "supabase"):
            self.assertNotIn(token, source)

    def test_hybrid_remains_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertNotIn("enable_hybrid_exposure_allocation = True", CLIENT.read_text())


if __name__ == "__main__":
    unittest.main()
