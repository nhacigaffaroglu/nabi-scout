from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from repositories.wealth_contribution_reconciliation_repository import (
    WealthContributionReconciliationRepository,
)
from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_CORPORATE_ACTION,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
    WealthValidationError,
)
from services.wealth_performance_engine import aggregate_cash_flows


FLOW_DEPOSIT = "DEPOSIT"
FLOW_WITHDRAWAL = "WITHDRAWAL"
EXTERNAL_FLOW_TYPES = frozenset({FLOW_DEPOSIT, FLOW_WITHDRAWAL})
_LEDGER_BY_FLOW = {
    FLOW_DEPOSIT: TXN_TYPE_DEPOSIT,
    FLOW_WITHDRAWAL: TXN_TYPE_WITHDRAW,
}
INVESTMENT_LOT_TYPES = frozenset({TXN_TYPE_BUY, TXN_TYPE_SELL})
NON_CONTRIBUTION_TYPES = frozenset(
    {
        TXN_TYPE_BUY,
        TXN_TYPE_SELL,
        TXN_TYPE_DIVIDEND,
        TXN_TYPE_FEE,
        TXN_TYPE_TRANSFER_IN,
        TXN_TYPE_TRANSFER_OUT,
        TXN_TYPE_CORPORATE_ACTION,
    }
)
RECONCILIATION_PROVENANCE = "USER_DEFINED"
CONTRIBUTION_TRACKING_UNCONFIGURED_COPY = (
    "Katkı takibi başlangıç tarihi henüz belirlenmedi."
)
CONTRIBUTION_TRACKING_NOT_TRACKED_COPY = "Bu dönem katkı takibi kapsamı dışında."
CONTRIBUTION_TRACKING_MID_PERIOD_COPY = (
    "Katkı takibi bu dönemde başladı; planlanan aylık tutar prorata edilmez."
)
CONTRIBUTION_ENTRY_BEFORE_START_COPY = (
    "İşlem tarihi katkı takibi başlangıcından önce; katkı takibi bu tarihte başlamamıştı."
)
CONTRIBUTION_RECON_BEFORE_START_COPY = (
    "Mutabakat tarihi katkı takibi başlangıcından önce olamaz."
)
CONTRIBUTION_TRACKING_LOCKED_COPY = (
    "Katkı takibi başlangıcı, kayıt veya mutabakat sonrası değiştirilemez."
)


class ContributionTrackingScope(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    NOT_TRACKED = "NOT_TRACKED"
    TRACKED = "TRACKED"


class ExternalCashFlowType(str, Enum):
    DEPOSIT = FLOW_DEPOSIT
    WITHDRAWAL = FLOW_WITHDRAWAL


@dataclass(frozen=True)
class ContributionReconciliation:
    portfolio_id: str
    reconciled_through: date
    provenance: str = RECONCILIATION_PROVENANCE
    notes: Optional[str] = None
    id: Optional[str] = None

    def covers(self, period_end: date) -> bool:
        return self.reconciled_through >= period_end


def parse_contribution_tracking_start(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text or text[:1] == "<":
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def tracking_boundary_start(tracking_start: date) -> datetime:
    return datetime.combine(tracking_start, time.min, tzinfo=timezone.utc) - timedelta(
        microseconds=1
    )


def resolve_tracked_window(
    start: datetime,
    end: datetime,
    tracking_start: Optional[date],
) -> Tuple[ContributionTrackingScope, Optional[datetime], Optional[datetime]]:
    if tracking_start is None:
        return ContributionTrackingScope.UNCONFIGURED, None, None
    if end.date() < tracking_start:
        return ContributionTrackingScope.NOT_TRACKED, None, None
    return (
        ContributionTrackingScope.TRACKED,
        max(start, tracking_boundary_start(tracking_start)),
        end,
    )


def tracked_ytd_month_count(as_of: date, tracking_start: date) -> int:
    if as_of < tracking_start:
        return 0
    first = (
        date(as_of.year, 1, 1)
        if tracking_start.year < as_of.year
        else date(tracking_start.year, tracking_start.month, 1)
    )
    if first.year != as_of.year:
        return 0
    return as_of.month - first.month + 1


def period_starts_mid_tracking_month(as_of: date, tracking_start: date) -> bool:
    return (
        tracking_start.year == as_of.year
        and tracking_start.month == as_of.month
        and tracking_start.day > 1
    )


def normalize_external_flow_type(flow_type: str) -> str:
    raw = str(flow_type or "").strip().upper()
    if raw in {"WITHDRAW", "WITHDRAWAL"}:
        raw = FLOW_WITHDRAWAL
    if raw not in EXTERNAL_FLOW_TYPES:
        raise WealthValidationError("Harici nakit akışı yalnızca DEPOSIT veya WITHDRAWAL olabilir.")
    return raw


def _parse_amount(amount: Any) -> Decimal:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WealthValidationError("Tutar sayısal olmalı.") from exc
    if value <= 0:
        raise WealthValidationError("Tutar sıfırdan büyük olmalı.")
    return value


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def period_is_reconciled(
    reconciliations: Sequence[ContributionReconciliation] | None,
    *,
    period_end: date,
    portfolio_id: Optional[str] = None,
) -> bool:
    for row in reconciliations or ():
        if portfolio_id and str(row.portfolio_id) != str(portfolio_id):
            continue
        if row.covers(period_end):
            return True
    return False


def contribution_period_evidence(
    transactions: Sequence[Dict[str, Any]],
    *,
    account_ids: set[str],
    plan_currency: str,
    start: datetime,
    end: datetime,
    reconciliations: Sequence[ContributionReconciliation] | None = None,
    portfolio_id: Optional[str] = None,
) -> str:
    """Truthful period evidence. Row existence is not completeness."""
    if period_is_reconciled(
        reconciliations,
        period_end=end.date(),
        portfolio_id=portfolio_id,
    ):
        return "COMPLETE"
    plan_ccy = plan_currency.strip().upper()
    plan_ccy_external = 0
    other_ccy_external = 0
    investment_lots = 0
    for row in transactions:
        if str(row.get("account_id") or "") not in account_ids:
            continue
        executed = _parse_ts(row.get("executed_at"))
        if executed is None or not (start < executed <= end):
            continue
        txn_type = str(row.get("txn_type") or "").strip().lower()
        if txn_type in INVESTMENT_LOT_TYPES:
            investment_lots += 1
        if txn_type not in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW}:
            continue
        currency = str(row.get("currency") or "").strip().upper()
        if currency == plan_ccy:
            plan_ccy_external += 1
        else:
            other_ccy_external += 1
    if plan_ccy_external > 0 or other_ccy_external > 0 or investment_lots > 0:
        return "PARTIAL"
    return "UNAVAILABLE"


def net_external_contribution(
    transactions: Iterable[Dict[str, Any]],
    *,
    account_ids: set[str],
    currency: str,
    period_start: datetime,
    period_end: datetime,
) -> Tuple[Decimal, Decimal, Decimal]:
    """Returns deposit total, withdrawal total, net (deposits - withdrawals) in `currency`."""
    inflows, outflows, _div, _fee, _warnings = aggregate_cash_flows(
        transactions,
        account_ids=account_ids,
        base_currency=currency,
        period_start=period_start,
        period_end=period_end,
    )
    deposits = Decimal(str(inflows))
    withdrawals = Decimal(str(outflows))
    return deposits, withdrawals, deposits - withdrawals


def contribution_delta_for_transaction(
    row: Dict[str, Any],
    *,
    plan_currency: str,
) -> Decimal:
    """Signed contribution of one stored ledger row. Trades/income/fees are 0."""
    txn_type = str(row.get("txn_type") or "").strip().lower()
    if txn_type in NON_CONTRIBUTION_TYPES:
        return Decimal("0")
    if txn_type not in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW}:
        return Decimal("0")
    currency = str(row.get("currency") or "").strip().upper()
    if currency != plan_currency.strip().upper():
        return Decimal("0")
    amount = Decimal(str(row.get("amount") or 0))
    if txn_type == TXN_TYPE_DEPOSIT:
        return amount
    return -amount


def reconciliation_from_row(row: Dict[str, Any]) -> ContributionReconciliation:
    through = row.get("reconciled_through")
    if isinstance(through, date) and not isinstance(through, datetime):
        parsed = through
    else:
        parsed = date.fromisoformat(str(through)[:10])
    return ContributionReconciliation(
        portfolio_id=str(row.get("portfolio_id") or ""),
        reconciled_through=parsed,
        provenance=str(row.get("provenance") or RECONCILIATION_PROVENANCE),
        notes=row.get("notes"),
        id=None if row.get("id") is None else str(row.get("id")),
    )


def record_external_cash_flow(
    wealth,
    *,
    portfolio_id: str,
    account_id: str,
    flow_type: str,
    amount: Any,
    currency: str,
    occurred_at: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Append-only external cash flow. Does not reverse, update, or infer from trades."""
    normalized_flow = normalize_external_flow_type(flow_type)
    value = _parse_amount(amount)
    ccy = str(currency or "").strip().upper()
    if not ccy:
        raise WealthValidationError("Para birimi gerekli.")
    account = wealth.accounts.get_by_id(wealth.user_id, account_id)
    if account is None:
        raise WealthValidationError("Hesap bulunamadı.")
    if str(account.get("portfolio_id") or "") != str(portfolio_id):
        raise WealthValidationError("Hesap bu portföye ait değil.")
    owned = any(str(row.get("id") or "") == str(portfolio_id) for row in wealth.portfolios.list_for_user(wealth.user_id))
    if not owned:
        raise WealthValidationError("Portföy bulunamadı.")
    cash = wealth.ensure_cash_asset(ccy)
    return wealth.post_transaction(
        account_id=account_id,
        asset_id=str(cash["id"]),
        txn_type=_LEDGER_BY_FLOW[normalized_flow],
        quantity=0,
        amount=float(value),
        currency=ccy,
        executed_at=occurred_at,
        notes=notes,
    )


def record_tracked_external_cash_flow(
    wealth,
    *,
    portfolio_id: str,
    account_id: str,
    flow_type: str,
    amount: Any,
    currency: str,
    occurred_at: str,
    tracking_start: Optional[date],
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Contribution-plan entry path. Rejects dates before tracking start."""
    if tracking_start is None:
        raise WealthValidationError(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
    parsed = _parse_ts(occurred_at)
    if parsed is None:
        raise WealthValidationError("İşlem tarihi gerekli.")
    if parsed.date() < tracking_start:
        raise WealthValidationError(CONTRIBUTION_ENTRY_BEFORE_START_COPY)
    return record_external_cash_flow(
        wealth,
        portfolio_id=portfolio_id,
        account_id=account_id,
        flow_type=flow_type,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        notes=notes,
    )


def load_contribution_tracking_start(wealth, portfolio_id: Optional[str]) -> Optional[date]:
    if wealth is None or not str(portfolio_id or "").strip():
        return None
    try:
        rows = wealth.portfolios.list_for_user(wealth.user_id)
    except Exception:
        return None
    if not isinstance(rows, (list, tuple)):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") != str(portfolio_id):
            continue
        return parse_contribution_tracking_start(row.get("contribution_tracking_start_date"))
    return None


def has_tracked_external_flows(
    transactions: Sequence[Dict[str, Any]],
    *,
    account_ids: set[str],
    tracking_start: date,
) -> bool:
    boundary = tracking_boundary_start(tracking_start)
    for row in transactions:
        if str(row.get("account_id") or "") not in account_ids:
            continue
        txn_type = str(row.get("txn_type") or "").strip().lower()
        if txn_type not in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW}:
            continue
        executed = _parse_ts(row.get("executed_at"))
        if executed is not None and executed > boundary:
            return True
    return False


def set_contribution_tracking_start(
    wealth,
    *,
    portfolio_id: str,
    tracking_start: date,
    transactions: Sequence[Dict[str, Any]] = (),
    account_ids: Sequence[str] = (),
    reconciliations: Sequence[ContributionReconciliation] = (),
) -> Dict[str, Any]:
    if tracking_start.year < 1900:
        raise WealthValidationError("Katkı takibi başlangıç tarihi geçersiz.")
    current = load_contribution_tracking_start(wealth, portfolio_id)
    ids = {str(item) for item in account_ids if str(item or "").strip()}
    locked = bool(reconciliations) or (
        current is not None
        and has_tracked_external_flows(
            list(transactions), account_ids=ids, tracking_start=current
        )
    )
    if locked and current is not None and tracking_start != current:
        raise WealthValidationError(CONTRIBUTION_TRACKING_LOCKED_COPY)
    return wealth.portfolios.set_contribution_tracking_start_date(
        wealth.user_id, str(portfolio_id), tracking_start
    )


def load_contribution_reconciliations(
    client,
    user_id: str,
    portfolio_id: str,
) -> Tuple[ContributionReconciliation, ...]:
    """Read-only fetch. Missing table/row is empty evidence, not zero contribution."""
    if client is None or not str(user_id or "").strip() or not str(portfolio_id or "").strip():
        return ()
    try:
        row = WealthContributionReconciliationRepository(client).get_for_portfolio(
            str(user_id), str(portfolio_id)
        )
    except Exception:
        return ()
    if not isinstance(row, dict) or not row.get("reconciled_through"):
        return ()
    try:
        return (reconciliation_from_row(row),)
    except (TypeError, ValueError):
        return ()


def contribution_reconciliations_for_wealth(
    wealth,
    portfolio_id: Optional[str],
) -> Tuple[ContributionReconciliation, ...]:
    if wealth is None:
        return ()
    return load_contribution_reconciliations(
        getattr(wealth, "client", None),
        str(getattr(wealth, "user_id", "") or ""),
        str(portfolio_id or ""),
    )


def mark_contribution_reconciled(
    repo,
    *,
    user_id: str,
    portfolio_id: str,
    reconciled_through: date,
    notes: Optional[str] = None,
    tracking_start: Optional[date] = None,
) -> Dict[str, Any]:
    """User attestation that external cash flows are complete through a date.

    Does not create deposits/withdrawals. Does not move reconciled_through backward.
    Requires a contribution tracking start and rejects dates before that start.
    """
    if tracking_start is None:
        raise WealthValidationError(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
    if reconciled_through.year < 1900:
        raise WealthValidationError("Mutabakat tarihi geçersiz.")
    if reconciled_through < tracking_start:
        raise WealthValidationError(CONTRIBUTION_RECON_BEFORE_START_COPY)
    return repo.upsert(
        user_id=user_id,
        portfolio_id=portfolio_id,
        reconciled_through=reconciled_through,
        provenance=RECONCILIATION_PROVENANCE,
        notes=notes,
    )
