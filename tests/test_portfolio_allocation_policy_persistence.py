from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import TestCase
from unittest.mock import MagicMock, patch

from components.portfolio_allocation_center_ui import (
    APPLIED_WEIGHTS_KEY,
    HYDRATED_KEY,
    LOAD_ERROR_KEY,
    PERSISTED_FLAG_KEY,
    PERSISTED_STATUS,
    SETTINGS_UNAVAILABLE,
    draft_weight_key,
    flatten_allocation_text,
    hydrate_allocation_session,
    present_allocation_center,
    render_portfolio_allocation_center,
    reset_allocation_policy_session,
    save_allocation_policy_from_session,
)
from repositories.portfolio_allocation_policy_repository import (
    PortfolioAllocationPolicyRepository,
)
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationPolicyStatus,
    AllocationProvenance,
    AllocationTarget,
    allocation_decision_signals,
    build_allocation_intelligence,
)
from services.portfolio_allocation_policy_service import (
    FORBIDDEN_DERIVED_KEYS,
    PERSISTED_PAYLOAD_KEYS,
    AllocationPolicyStoreError,
    PortfolioAllocationPolicyService,
    policy_from_record,
    policy_record_payload,
)
from services.wealth_contract import WealthValidationError
from tests.test_portfolio_allocation_intelligence import _complete_usd_view, _partial_bist_view


MIGRATION = Path("database/migration_portfolio_allocation_policies.sql")
ENGINE = Path("services/portfolio_allocation_intelligence.py")
DECISION = Path("services/portfolio_decision_intelligence.py")
UI = Path("components/portfolio_allocation_center_ui.py")
USER_A = "user-a"
USER_B = "user-b"
PF_A = "pf-a"
PF_B = "pf-b"
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)


class _Result:
    def __init__(self, data: Optional[List[Dict[str, Any]]]) -> None:
        self.data = data


class FakeAllocationClient:
    def __init__(self, *, missing_table: bool = False) -> None:
        self.missing_table = missing_table
        self.rows: List[Dict[str, Any]] = []
        self.write_log: List[str] = []

    def table(self, name: str) -> "FakeAllocationQuery":
        if name != "portfolio_allocation_policies" or self.missing_table:
            raise RuntimeError(f"relation {name} does not exist")
        return FakeAllocationQuery(self)


class FakeAllocationQuery:
    def __init__(self, client: FakeAllocationClient) -> None:
        self.client = client
        self.filters: Dict[str, Any] = {}
        self.op = "select"
        self.payload: Optional[Dict[str, Any]] = None
        self._limit: Optional[int] = None

    def select(self, *_args: Any) -> "FakeAllocationQuery":
        self.op = "select"
        return self

    def eq(self, key: str, value: Any) -> "FakeAllocationQuery":
        self.filters[key] = value
        return self

    def limit(self, count: int) -> "FakeAllocationQuery":
        self._limit = count
        return self

    def insert(self, body: Dict[str, Any]) -> "FakeAllocationQuery":
        self.op = "insert"
        self.payload = dict(body)
        return self

    def update(self, body: Dict[str, Any]) -> "FakeAllocationQuery":
        self.op = "update"
        self.payload = dict(body)
        return self

    def delete(self) -> "FakeAllocationQuery":
        self.op = "delete"
        return self

    def _matches(self, row: Dict[str, Any]) -> bool:
        return all(row.get(key) == value for key, value in self.filters.items())

    def execute(self) -> _Result:
        rows = self.client.rows
        if self.op == "select":
            found = [dict(row) for row in rows if self._matches(row)]
            if self._limit is not None:
                found = found[: self._limit]
            return _Result(found)
        if self.op == "insert":
            self.client.write_log.append("insert")
            row = dict(self.payload or {})
            row.setdefault("id", f"id-{len(rows) + 1}")
            if "targets" in row:
                row["targets"] = [dict(item) for item in row["targets"]]
            rows.append(row)
            return _Result([dict(row)])
        if self.op == "update":
            self.client.write_log.append("update")
            updated: List[Dict[str, Any]] = []
            for row in rows:
                if self._matches(row):
                    row.update(dict(self.payload or {}))
                    if "targets" in row:
                        row["targets"] = [dict(item) for item in row["targets"]]
                    updated.append(dict(row))
            return _Result(updated)
        if self.op == "delete":
            self.client.write_log.append("delete")
            kept = [row for row in rows if not self._matches(row)]
            self.client.rows = kept
            return _Result([])
        return _Result([])


def _policy(
    *,
    equity: float = 70.0,
    etf: float = 30.0,
    sukuk: float = 0.0,
    cash: float = 0.0,
    other: float = 0.0,
    provenance: AllocationProvenance = AllocationProvenance.USER_DEFINED,
) -> AllocationPolicy:
    return AllocationPolicy(
        targets=(
            AllocationTarget("equity", AllocationDimension.ASSET_CLASS, equity),
            AllocationTarget("etf", AllocationDimension.ASSET_CLASS, etf),
            AllocationTarget("sukuk", AllocationDimension.ASSET_CLASS, sukuk),
            AllocationTarget("cash", AllocationDimension.ASSET_CLASS, cash),
            AllocationTarget("other", AllocationDimension.ASSET_CLASS, other),
        ),
        provenance=provenance,
    )


def _draft_session(weights: Dict[str, float]) -> Dict[str, Any]:
    session: Dict[str, Any] = {}
    for bucket, value in weights.items():
        session[draft_weight_key(bucket)] = value
    return session


def _service(client: FakeAllocationClient, user_id: str = USER_A) -> PortfolioAllocationPolicyService:
    return PortfolioAllocationPolicyService(client, user_id)


class MigrationContractTests(TestCase):
    def test_dedicated_table_rls_and_unique_portfolio_policy(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        lowered = sql.lower()
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)
        self.assertIn("create table if not exists public.portfolio_allocation_policies", lowered)
        self.assertIn(
            "constraint portfolio_allocation_policies_user_portfolio_uidx unique (user_id, portfolio_id)",
            lowered,
        )
        self.assertIn("enable row level security", lowered)
        self.assertIn("jsonb not null", lowered)
        self.assertIn("auth.uid() = user_id", lowered)
        self.assertNotIn("drop table", lowered)
        self.assertNotIn("truncate", lowered)
        self.assertNotIn("observable_weight", lowered)
        self.assertNotIn("before_drift", lowered)
        self.assertNotIn("\n    routing ", lowered)
        self.assertNotIn("routing jsonb", lowered)


class EconomicExposureDimensionMigrationTests(TestCase):
    def test_additive_check_constraint_migration(self) -> None:
        sql = Path("database/migration_portfolio_allocation_policies_economic_exposure.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)
        self.assertIn("drop constraint if exists portfolio_allocation_policies_dimension_check", sql)
        self.assertIn(
            "check (dimension in ('ASSET_CLASS', 'MARKET', 'ECONOMIC_EXPOSURE'))",
            sql,
        )
        self.assertNotIn("create table", sql.lower())
        self.assertNotIn("drop table", sql.lower())
        self.assertNotIn("truncate", sql.lower())
        original = MIGRATION.read_text(encoding="utf-8")
        self.assertNotIn("ECONOMIC_EXPOSURE", original)


class RepositoryServiceTests(TestCase):
    def test_no_row_means_not_configured(self) -> None:
        service = _service(FakeAllocationClient())
        self.assertIsNone(service.get_policy(PF_A))
        view = build_allocation_intelligence(_complete_usd_view(), policy=service.get_policy(PF_A))
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)

    def test_economic_exposure_dimension_accepted_and_unknown_rejected(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        policy = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ECONOMIC_EXPOSURE, 70),
                AllocationTarget("sukuk", AllocationDimension.ECONOMIC_EXPOSURE, 30),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        payload = policy_record_payload(policy)
        self.assertEqual(payload["dimension"], "ECONOMIC_EXPOSURE")
        saved = service.save_policy(PF_A, policy)
        self.assertEqual(saved.targets[0].dimension, AllocationDimension.ECONOMIC_EXPOSURE)
        with self.assertRaises(WealthValidationError):
            AllocationTarget("unknown", AllocationDimension.ECONOMIC_EXPOSURE, 100).validate()
        invalid_total = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ECONOMIC_EXPOSURE, 70),
                AllocationTarget("cash", AllocationDimension.ECONOMIC_EXPOSURE, 20),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        with self.assertRaises(WealthValidationError):
            service.save_policy(PF_B, invalid_total)
        self.assertEqual(len(client.rows), 1)

    def test_growth_economic_exposure_round_trips(self) -> None:
        from components.portfolio_economic_exposure_ui import (
            GROWTH_ECONOMIC_EXPOSURE_WEIGHTS,
            growth_economic_exposure_policy,
            hydrate_economic_exposure_from_policy,
            weights_from_exposure_policy,
        )

        client = FakeAllocationClient()
        service = _service(client)
        saved = service.save_policy(PF_A, growth_economic_exposure_policy())
        loaded = service.get_policy(PF_A)
        self.assertEqual(loaded, saved)
        self.assertEqual(policy_record_payload(loaded)["dimension"], "ECONOMIC_EXPOSURE")
        self.assertEqual(loaded.provenance, AllocationProvenance.USER_DEFINED)
        weights = weights_from_exposure_policy(loaded)
        self.assertEqual(weights, GROWTH_ECONOMIC_EXPOSURE_WEIGHTS)
        session: Dict[str, Any] = {}
        hydrate_allocation_session(session, policy_service=service, portfolio_id=PF_A)
        self.assertNotIn(APPLIED_WEIGHTS_KEY, session)
        self.assertFalse(session.get(PERSISTED_FLAG_KEY))
        hydrate_economic_exposure_from_policy(session, loaded)
        self.assertEqual(session["portfolio_economic_exposure_applied_weights"]["equity"], 75.0)

    def test_valid_user_defined_policy_saves_and_round_trips(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        saved = service.save_policy(PF_A, _policy())
        loaded = service.get_policy(PF_A)
        self.assertEqual(saved.provenance, AllocationProvenance.USER_DEFINED)
        self.assertEqual(loaded, saved)
        self.assertEqual(policy_record_payload(loaded), policy_record_payload(saved))
        self.assertEqual(len(client.rows), 1)

    def test_update_replaces_prior_policy_deterministically(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        service.save_policy(PF_A, _policy(equity=70, etf=30))
        updated = service.save_policy(PF_A, _policy(equity=60, etf=40))
        loaded = service.get_policy(PF_A)
        self.assertEqual(len(client.rows), 1)
        self.assertEqual(loaded, updated)
        weights = {row.bucket_id: row.target_weight_pct for row in loaded.targets}
        self.assertEqual(weights["equity"], 60.0)
        self.assertEqual(weights["etf"], 40.0)

    def test_invalid_total_negative_and_duplicate_do_not_write(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        invalid_total = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 70),
                AllocationTarget("etf", AllocationDimension.ASSET_CLASS, 20),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        negative = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, -1),
                AllocationTarget("etf", AllocationDimension.ASSET_CLASS, 101),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        duplicate = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 50),
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 50),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        for policy in (invalid_total, negative, duplicate):
            with self.assertRaises(WealthValidationError):
                service.save_policy(PF_A, policy)
        self.assertEqual(client.write_log, [])
        self.assertEqual(client.rows, [])
        self.assertIsNone(service.get_policy(PF_A))

    def test_reset_returns_unconfigured(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        service.save_policy(PF_A, _policy())
        service.delete_policy(PF_A)
        self.assertIsNone(service.get_policy(PF_A))
        view = build_allocation_intelligence(_complete_usd_view(), policy=service.get_policy(PF_A))
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)

    def test_no_cross_portfolio_or_cross_user_leakage(self) -> None:
        client = FakeAllocationClient()
        service_a = _service(client, USER_A)
        service_b = _service(client, USER_B)
        service_a.save_policy(PF_A, _policy(equity=70, etf=30))
        self.assertIsNone(service_a.get_policy(PF_B))
        self.assertIsNone(service_b.get_policy(PF_A))
        service_b.save_policy(PF_B, _policy(equity=40, etf=60))
        loaded_a = service_a.get_policy(PF_A)
        loaded_b = service_b.get_policy(PF_B)
        self.assertEqual({row.bucket_id: row.target_weight_pct for row in loaded_a.targets}["equity"], 70)
        self.assertEqual({row.bucket_id: row.target_weight_pct for row in loaded_b.targets}["equity"], 40)
        self.assertEqual(len(client.rows), 2)

    def test_derived_drift_and_routing_are_not_persisted(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        service.save_policy(PF_A, _policy())
        row = client.rows[0]
        self.assertEqual(set(policy_record_payload(_policy())), PERSISTED_PAYLOAD_KEYS)
        for key in FORBIDDEN_DERIVED_KEYS:
            self.assertNotIn(key, row)
            self.assertNotIn(key, row["targets"][0])
        view = build_allocation_intelligence(_partial_bist_view(), policy=service.get_policy(PF_A))
        self.assertTrue(view.drift)
        self.assertTrue(view.routing)
        self.assertNotIn("drift", row)
        self.assertNotIn("routing", row)

    def test_missing_table_is_store_error_not_fabricated_target(self) -> None:
        service = _service(FakeAllocationClient(missing_table=True))
        with self.assertRaises(AllocationPolicyStoreError):
            service.get_policy(PF_A)


class UiPersistenceTests(TestCase):
    def test_hydrate_empty_store_leaves_unconfigured(self) -> None:
        session: Dict[str, Any] = {}
        hydrate_allocation_session(
            session, policy_service=_service(FakeAllocationClient()), portfolio_id=PF_A
        )
        self.assertFalse(session.get(PERSISTED_FLAG_KEY))
        self.assertNotIn(APPLIED_WEIGHTS_KEY, session)
        view = build_allocation_intelligence(_complete_usd_view())
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)

    def test_explicit_save_writes_once_and_session_agrees(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        session = _draft_session(
            {"equity": 70, "etf": 30, "sukuk": 0, "cash": 0, "other": 0}
        )
        error = save_allocation_policy_from_session(
            session, policy_service=service, portfolio_id=PF_A
        )
        self.assertIsNone(error)
        self.assertEqual(client.write_log, ["insert"])
        self.assertEqual(session[APPLIED_WEIGHTS_KEY]["equity"], 70)
        self.assertTrue(session[PERSISTED_FLAG_KEY])
        loaded = service.get_policy(PF_A)
        self.assertEqual(loaded.provenance, AllocationProvenance.USER_DEFINED)

    def test_draft_does_not_autosave_and_failed_save_keeps_draft(self) -> None:
        service = MagicMock()
        service.get_policy.return_value = None
        service.save_policy.side_effect = AllocationPolicyStoreError("Hedef dağılım kaydedilemedi.")
        session = _draft_session(
            {"equity": 70, "etf": 30, "sukuk": 0, "cash": 0, "other": 0}
        )
        hydrate_allocation_session(session, policy_service=service, portfolio_id=PF_A)
        self.assertEqual(service.save_policy.call_count, 0)
        self.assertEqual(service.delete_policy.call_count, 0)
        error = save_allocation_policy_from_session(
            session, policy_service=service, portfolio_id=PF_A
        )
        self.assertIsNotNone(error)
        self.assertEqual(session[draft_weight_key("equity")], 70)
        self.assertNotIn(APPLIED_WEIGHTS_KEY, session)
        self.assertEqual(service.save_policy.call_count, 1)

    def test_failed_reset_does_not_clear_session(self) -> None:
        service = MagicMock()
        service.delete_policy.side_effect = AllocationPolicyStoreError("Hedef sıfırlanamadı.")
        session = {
            APPLIED_WEIGHTS_KEY: {"equity": 70, "etf": 30, "sukuk": 0, "cash": 0, "other": 0},
            PERSISTED_FLAG_KEY: True,
            draft_weight_key("equity"): 70,
            draft_weight_key("etf"): 30,
        }
        error = reset_allocation_policy_session(session, policy_service=service, portfolio_id=PF_A)
        self.assertIsNotNone(error)
        self.assertIn(APPLIED_WEIGHTS_KEY, session)
        self.assertTrue(session[PERSISTED_FLAG_KEY])

    def test_reset_clears_persisted_and_session(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        service.save_policy(PF_A, _policy())
        session = _draft_session(
            {"equity": 70, "etf": 30, "sukuk": 0, "cash": 0, "other": 0}
        )
        session[APPLIED_WEIGHTS_KEY] = {
            "equity": 70,
            "etf": 30,
            "sukuk": 0,
            "cash": 0,
            "other": 0,
        }
        error = reset_allocation_policy_session(session, policy_service=service, portfolio_id=PF_A)
        self.assertIsNone(error)
        self.assertIsNone(service.get_policy(PF_A))
        self.assertNotIn(APPLIED_WEIGHTS_KEY, session)
        self.assertFalse(session[PERSISTED_FLAG_KEY])

    def test_new_session_loads_persisted_policy(self) -> None:
        client = FakeAllocationClient()
        service = _service(client)
        service.save_policy(PF_A, _policy(equity=55, etf=45))
        fresh: Dict[str, Any] = {}
        hydrate_allocation_session(fresh, policy_service=service, portfolio_id=PF_A)
        self.assertTrue(fresh[PERSISTED_FLAG_KEY])
        self.assertEqual(fresh[APPLIED_WEIGHTS_KEY]["equity"], 55)
        self.assertEqual(fresh[draft_weight_key("etf")], 45)
        view = build_allocation_intelligence(
            _complete_usd_view(),
            policy=policy_from_record(client.rows[0]),
        )
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.CONFIGURED)
        presented = present_allocation_center(view, persisted=True)
        self.assertIn(PERSISTED_STATUS, flatten_allocation_text(presented))

    def test_load_failure_keeps_observable_without_target(self) -> None:
        session: Dict[str, Any] = {}
        hydrate_allocation_session(
            session,
            policy_service=_service(FakeAllocationClient(missing_table=True)),
            portfolio_id=PF_A,
        )
        self.assertEqual(session[LOAD_ERROR_KEY], SETTINGS_UNAVAILABLE)
        self.assertNotIn(APPLIED_WEIGHTS_KEY, session)
        view = build_allocation_intelligence(_partial_bist_view())
        presented = present_allocation_center(
            view,
            settings_unavailable=True,
            persistence_message=session[LOAD_ERROR_KEY],
        )
        self.assertFalse(presented.configured)
        self.assertTrue(any(row.observable_weight_pct for row in presented.rows))
        self.assertIn(SETTINGS_UNAVAILABLE, flatten_allocation_text(presented))

    def test_render_does_not_write_policy(self) -> None:
        service = MagicMock()
        service.get_policy.return_value = None

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def number_input(self, *a, **k):
                return 0

            def button(self, *a, **k):
                return False

            def markdown(self, message, **_k):
                return None

            def caption(self, message, **_k):
                return None

            def info(self, message, **_k):
                return None

            def selectbox(self, *a, **k):
                return "USD"

            def radio(self, *a, **k):
                options = k.get("options") or (a[1] if len(a) > 1 else ["ASSET_CLASS"])
                return options[0]

            def altair_chart(self, *a, **k):
                return None

        class _St(_Ctx):
            def columns(self, n, **_k):
                count = n if isinstance(n, int) else len(n)
                return [_Ctx() for _ in range(count)]

            def rerun(self):
                return None

        fake = _St()
        state: Dict[str, Any] = {}
        with patch.dict("sys.modules", {"streamlit": fake}), patch(
            "components.nabi_design_system._st", return_value=fake
        ):
            presented = render_portfolio_allocation_center(
                allocation=build_allocation_intelligence(_complete_usd_view()),
                session_state=state,
                policy_service=service,
                portfolio_id=PF_A,
            )
        self.assertIsNotNone(presented)
        service.save_policy.assert_not_called()
        service.delete_policy.assert_not_called()
        self.assertEqual(service.get_policy.call_count, 1)
        self.assertIn(HYDRATED_KEY, state)

    def test_decision_signals_compatible_and_not_wired(self) -> None:
        policy = _policy()
        view = build_allocation_intelligence(_partial_bist_view(), policy=policy)
        signals = allocation_decision_signals(view)
        self.assertEqual(signals.target_status, AllocationPolicyStatus.CONFIGURED)
        self.assertTrue(signals.allocation_evidence_incomplete)
        decision = DECISION.read_text(encoding="utf-8")
        self.assertIn("AllocationDecisionSignals", decision)
        self.assertNotIn("portfolio_allocation_policy_service", decision)
        self.assertNotIn(".insert(", decision)

    def test_provider_tokens_absent_from_persistence_surface(self) -> None:
        for path in (
            Path("services/portfolio_allocation_policy_service.py"),
            Path("repositories/portfolio_allocation_policy_repository.py"),
            UI,
            ENGINE,
        ):
            raw = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, raw)


class RepositoryQueryTests(TestCase):
    def test_get_scopes_to_user_and_portfolio(self) -> None:
        client = MagicMock()
        chain = client.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.limit.return_value.execute.return_value.data = []
        repo = PortfolioAllocationPolicyRepository(client)
        self.assertIsNone(repo.get_for_portfolio(USER_A, PF_A))
        chain.eq.assert_any_call("user_id", USER_A)
        chain.eq.assert_any_call("portfolio_id", PF_A)
