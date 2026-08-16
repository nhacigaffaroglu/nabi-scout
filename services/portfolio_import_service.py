from __future__ import annotations

from typing import Iterable, List, Tuple

from services.wealth_contract import (
    ACCOUNT_TYPE_BROKERAGE,
    ASSET_CLASS_EQUITY,
    TXN_TYPE_BUY,
    WealthValidationError,
)
from services.wealth_core_service import WealthCoreService


def position_quantity_for_symbol(
    wealth: WealthCoreService,
    symbol: str,
) -> Tuple[float, bool]:
    assets = wealth.list_assets()
    asset_by_id = {row["id"]: row for row in assets}
    total = 0.0
    found = False
    for position in wealth.list_positions():
        asset = asset_by_id.get(position.get("asset_id"), {})
        if str(asset.get("symbol") or "").strip().upper() == symbol:
            total += float(position.get("quantity") or 0.0)
            found = True
    return total, found


def ensure_brokerage_account(wealth: WealthCoreService, currency: str) -> dict:
    accounts = wealth.list_accounts()
    for account in accounts:
        if (
            account.get("account_type") == ACCOUNT_TYPE_BROKERAGE
            and str(account.get("currency") or "").upper() == currency.upper()
        ):
            return account
    return wealth.create_account(
        name=f"Import ({currency})",
        account_type=ACCOUNT_TYPE_BROKERAGE,
        currency=currency,
    )


def import_portfolio_rows(
    wealth: WealthCoreService,
    rows: Iterable[dict],
    *,
    dry_run: bool = False,
) -> dict:
    summary = {"imported": 0, "skipped": 0, "warnings": []}
    for row in rows:
        symbol = row["symbol"]
        quantity = float(row["quantity"])
        average_cost = float(row["average_cost"])
        currency = row["currency"]

        existing_qty, found = position_quantity_for_symbol(wealth, symbol)
        if found and abs(existing_qty - quantity) < 1e-6:
            summary["skipped"] += 1
            continue
        if found:
            summary["warnings"].append(
                f"{symbol}: mevcut miktar {existing_qty}, CSV {quantity} — atlandı."
            )
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["imported"] += 1
            continue

        account = ensure_brokerage_account(wealth, currency)
        asset = wealth.register_asset(
            symbol=symbol,
            market="US",
            asset_class=ASSET_CLASS_EQUITY,
            currency=currency,
        )
        amount = quantity * average_cost
        wealth.post_transaction(
            account_id=str(account["id"]),
            txn_type=TXN_TYPE_BUY,
            quantity=quantity,
            amount=amount,
            currency=currency,
            asset_id=str(asset["id"]),
            price=average_cost,
            notes="import_portfolio.py",
        )
        summary["imported"] += 1
    return summary
