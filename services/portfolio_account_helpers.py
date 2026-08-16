from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_account_display(account: Optional[Dict[str, Any]]) -> str:
    if not account:
        return "—"
    institution = str(account.get("institution") or "").strip()
    label = str(account.get("name") or "").strip()
    if institution and label:
        return f"{institution} — {label}"
    if institution:
        return institution
    if label:
        return label
    return str(account.get("id") or "—")


def accounts_for_portfolio(
    accounts: List[Dict[str, Any]],
    portfolio_id: str,
    *,
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    rows = [
        row
        for row in accounts
        if str(row.get("portfolio_id") or "") == str(portfolio_id)
    ]
    if active_only:
        rows = [row for row in rows if row.get("is_active", True)]
    return sorted(rows, key=lambda row: format_account_display(row).casefold())


def account_filter_options(accounts: List[Dict[str, Any]]) -> List[tuple[str, str]]:
    """Return (display_label, account_id) pairs for selectbox."""
    return [(format_account_display(row), str(row["id"])) for row in accounts]
