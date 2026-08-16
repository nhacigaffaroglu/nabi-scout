#!/usr/bin/env python3
"""Live verification for account-scoped portfolio management."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_management_service import PortfolioManagementService
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_core_service import WealthCoreService

TEST_INSTITUTIONS = ("NABI TEST MIDAS", "NABI TEST YKB")
TEST_SYMBOL = "CRM"


def _snapshot_state(wealth: WealthCoreService) -> dict:
    return {
        "accounts": wealth.list_accounts(),
        "positions": wealth.list_positions(),
        "transactions": wealth.list_transactions(limit=500),
    }


def _find_test_accounts(accounts: list) -> dict:
    found = {}
    for row in accounts:
        institution = str(row.get("institution") or "").strip().upper()
        for name in TEST_INSTITUTIONS:
            if institution == name.upper():
                found[name] = row
    return found


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    before = _snapshot_state(wealth)

    llm_calls = {"count": 0}
    fmp_calls = {"count": 0}

    def _block_llm(*_a, **_k):
        llm_calls["count"] += 1
        raise RuntimeError("LLM blocked")

    def _block_fmp(*_a, **_k):
        fmp_calls["count"] += 1
        raise RuntimeError("FMP blocked")

    results: dict = {"user_id": user_id, "steps": []}

    mgmt = PortfolioManagementService(wealth)
    test_accounts = {}
    for institution in TEST_INSTITUTIONS:
        existing = _find_test_accounts(wealth.list_accounts()).get(institution)
        if existing:
            test_accounts[institution] = existing
        else:
            test_accounts[institution] = mgmt.create_institution_account(
                institution=institution,
                account_label="Live Verify",
                currency="USD",
                portfolio_id=str(portfolio["id"]),
            )
            results["steps"].append(f"created_account:{institution}")

    midas_id = str(test_accounts["NABI TEST MIDAS"]["id"])
    ykb_id = str(test_accounts["NABI TEST YKB"]["id"])

    mgmt.add_holding(
        account_id=midas_id,
        symbol=TEST_SYMBOL,
        quantity=10.0,
        average_cost=250.0,
        currency="USD",
        notes="live-verify",
    )
    mgmt.add_holding(
        account_id=ykb_id,
        symbol=TEST_SYMBOL,
        quantity=5.0,
        average_cost=220.0,
        currency="USD",
        notes="live-verify",
    )
    results["steps"].append("added_crm_both_accounts")

    asset = wealth.register_asset(
        symbol=TEST_SYMBOL,
        market="US",
        asset_class="equity",
        currency="USD",
    )

    # Transfer 4 CRM Midas -> YKB (cost basis preserved @ 250 on transferred lot)
    mgmt.transfer_holding(
        from_account_id=midas_id,
        to_account_id=ykb_id,
        asset_id=str(asset["id"]),
        quantity=4.0,
        notes="live-verify-transfer",
    )
    results["steps"].append("transferred_crm_midas_to_ykb")

    positions_after_transfer = wealth.list_positions()
    crm_positions = [
        p for p in positions_after_transfer if str(p.get("asset_id")) == str(asset["id"])
    ]
    midas_pos = next(
        (p for p in crm_positions if str(p.get("account_id")) == midas_id),
        None,
    )
    ykb_pos = next(
        (p for p in crm_positions if str(p.get("account_id")) == ykb_id),
        None,
    )
    transfer_txns = [
        t
        for t in wealth.list_transactions(limit=500)
        if str(t.get("asset_id")) == str(asset["id"])
        and str(t.get("txn_type") or "") in {"transfer_out", "transfer_in"}
    ]
    results["transfer_verification"] = {
        "midas_qty": float(midas_pos.get("quantity") or 0) if midas_pos else None,
        "ykb_qty": float(ykb_pos.get("quantity") or 0) if ykb_pos else None,
        "combined_qty": sum(float(p.get("quantity") or 0) for p in crm_positions),
        "transfer_txn_count": len(transfer_txns),
        "transfer_txn_types": sorted({str(t.get("txn_type")) for t in transfer_txns}),
    }

    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service,
        nabi_client=client,
    )
    with patch("services.fmp_client.FMPClient.quote", side_effect=_block_fmp), patch(
        "services.wealth_adviser_llm_client.requests.post",
        side_effect=_block_llm,
    ):
        view = intelligence.build_view(portfolio, enrich_nabi=True)
        dashboard = build_portfolio_intelligence_dashboard(
            view,
            accounts_by_id={str(a["id"]): a for a in wealth.list_accounts()},
        )

    crm_rows = [
        row for row in dashboard.enriched_positions if row.valuation.symbol == TEST_SYMBOL
    ]
    consolidated = next(
        (row for row in dashboard.consolidated_symbols if row.symbol == TEST_SYMBOL),
        None,
    )
    results["verification"] = {
        "account_level_rows": len(crm_rows),
        "consolidated_quantity": consolidated.total_quantity if consolidated else None,
        "institution_allocation_count": len(dashboard.account_allocation),
        "llm_calls": llm_calls["count"],
        "fmp_calls": fmp_calls["count"],
        "candidate_price_fetches": price_service.fetch_count,
    }

    # Edit Midas CRM quantity 6 -> 4 via accounting-safe adjust
    mgmt.adjust_holding(
        account_id=midas_id,
        asset_id=str(asset["id"]),
        new_quantity=4.0,
        new_average_cost=250.0,
        notes="live-verify-edit",
    )
    results["steps"].append("edited_midas_crm")

    # Close YKB CRM
    mgmt.close_holding(account_id=ykb_id, asset_id=str(asset["id"]))
    results["steps"].append("closed_ykb_crm")

    # Close Midas CRM to restore no CRM exposure from test
    mgmt.close_holding(account_id=midas_id, asset_id=str(asset["id"]))
    results["steps"].append("closed_midas_crm")

    after = _snapshot_state(wealth)
    results["cleanup"] = {
        "test_accounts_remain": list(_find_test_accounts(after["accounts"]).keys()),
        "crm_positions_after": len(
            [
                p
                for p in after["positions"]
                if str(p.get("asset_id")) == str(asset["id"])
            ]
        ),
    }
    results["pre_existing_preserved"] = {
        "accounts_before": len(before["accounts"]),
        "accounts_after": len(after["accounts"]),
        "positions_before": len(before["positions"]),
        "positions_after": len(after["positions"]),
    }

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    ok = (
        results["transfer_verification"]["midas_qty"] == 6.0
        and results["transfer_verification"]["ykb_qty"] == 9.0
        and results["transfer_verification"]["combined_qty"] == 15.0
        and results["transfer_verification"]["transfer_txn_count"] == 2
        and results["transfer_verification"]["transfer_txn_types"]
        == ["transfer_in", "transfer_out"]
        and results["verification"]["account_level_rows"] == 2
        and results["verification"]["consolidated_quantity"] == 15.0
        and results["verification"]["llm_calls"] == 0
        and results["verification"]["fmp_calls"] == 0
        and results["cleanup"]["crm_positions_after"] == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
