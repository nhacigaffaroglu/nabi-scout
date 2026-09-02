from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

TXN_TYPE_BUY = "buy"
TXN_TYPE_SELL = "sell"
TXN_TYPE_DIVIDEND = "dividend"
TXN_TYPE_DEPOSIT = "deposit"
TXN_TYPE_WITHDRAW = "withdraw"
TXN_TYPE_FEE = "fee"
TXN_TYPE_TRANSFER_OUT = "transfer_out"
TXN_TYPE_TRANSFER_IN = "transfer_in"
TXN_TYPE_CORPORATE_ACTION = "corporate_action"

TXN_TYPES: Tuple[str, ...] = (
    TXN_TYPE_BUY,
    TXN_TYPE_SELL,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_WITHDRAW,
    TXN_TYPE_FEE,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_TRANSFER_IN,
)

TRANSFER_TXN_TYPES = frozenset({TXN_TYPE_TRANSFER_OUT, TXN_TYPE_TRANSFER_IN})
LEDGER_TXN_TYPES: Tuple[str, ...] = (*TXN_TYPES, TXN_TYPE_CORPORATE_ACTION)

ACCOUNT_TYPE_CASH = "cash"
ACCOUNT_TYPE_BROKERAGE = "brokerage"
ACCOUNT_TYPE_RETIREMENT = "retirement"
ACCOUNT_TYPE_OTHER = "other"

ASSET_CLASS_CASH = "cash"
ASSET_CLASS_EQUITY = "equity"
ASSET_CLASS_ETF = "etf"
ASSET_CLASS_FUND = "fund"
ASSET_CLASS_GOLD = "gold"
ASSET_CLASS_SUKUK = "sukuk"
ASSET_CLASS_OTHER = "other"

CASH_SYMBOL = "CASH"


class WealthValidationError(ValueError):
    """Invalid wealth core input or impossible ledger state."""


class WealthMaterializationError(RuntimeError):
    """Ledger row persisted but derived position state could not be updated."""


@dataclass(frozen=True)
class WealthPortfolio:
    id: str
    user_id: str
    name: str
    base_currency: str
    is_default: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthAccount:
    id: str
    user_id: str
    portfolio_id: str
    name: str
    account_type: str
    currency: str
    institution: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthAsset:
    id: str
    user_id: str
    symbol: str
    market: str
    asset_class: str
    currency: str
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthLiability:
    id: str
    user_id: str
    name: str
    liability_type: str
    currency: str
    principal: float
    portfolio_id: Optional[str] = None
    interest_rate: Optional[float] = None
    maturity_date: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthTransaction:
    id: str
    user_id: str
    account_id: str
    txn_type: str
    quantity: float
    amount: float
    currency: str
    asset_id: Optional[str] = None
    price: Optional[float] = None
    executed_at: Optional[str] = None
    notes: Optional[str] = None
    reversal_of_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthPosition:
    id: str
    user_id: str
    account_id: str
    asset_id: str
    quantity: float
    average_cost: float
    cost_currency: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BuyCostBasis:
    """Commission-aware BUY lot cost. Quantity is never increased by commission."""

    quantity: float
    unit_price: float
    commission: float
    gross_cost: float
    total_cost_basis: float
    effective_unit_cost: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_symbol(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def normalize_market(market: Optional[str]) -> str:
    return str(market or "US").strip().upper()


def validate_txn_type(txn_type: str) -> str:
    normalized = str(txn_type or "").strip().lower()
    if normalized not in LEDGER_TXN_TYPES:
        raise WealthValidationError(f"Geçersiz işlem türü: {txn_type}")
    return normalized


def compute_buy_cost_basis(
    quantity: float,
    unit_price: float,
    commission: Optional[float] = 0.0,
) -> BuyCostBasis:
    """gross_cost = qty × unit_price; total_cost_basis = gross + commission."""
    qty = float(quantity)
    price = float(unit_price)
    fee = 0.0 if commission is None else float(commission)
    if qty <= 0:
        raise WealthValidationError("Adet sıfırdan büyük olmalı.")
    if price <= 0:
        raise WealthValidationError("Alış/satış için birim fiyat gerekli.")
    if fee < 0:
        raise WealthValidationError("Komisyon negatif olamaz.")
    gross = qty * price
    total = gross + fee
    return BuyCostBasis(
        quantity=qty,
        unit_price=price,
        commission=fee,
        gross_cost=gross,
        total_cost_basis=total,
        effective_unit_cost=total / qty,
    )


def buy_commission_from_ledger(
    *,
    quantity: float,
    price: Optional[float],
    amount: float,
) -> float:
    """Recover commission encoded as BUY.amount − (quantity × execution price)."""
    qty = float(quantity or 0.0)
    unit = float(price or 0.0)
    total = float(amount or 0.0)
    if qty <= 0 or unit <= 0:
        return 0.0
    commission = total - (qty * unit)
    return commission if commission > 1e-12 else 0.0


def normalize_trade_amount(
    txn_type: str,
    *,
    quantity: float,
    price: Optional[float],
    amount: float,
) -> float:
    """Derive and validate monetary amount for buy/sell rows.

    SELL amount must equal quantity × price.
    BUY amount is total acquisition cost: quantity × execution price, plus
    optional commission. Commission must not change quantity.
    """
    if txn_type not in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
        return amount

    if quantity <= 0:
        raise WealthValidationError("Alış/satış için miktar sıfırdan büyük olmalı.")
    if price is None or price <= 0:
        raise WealthValidationError("Alış/satış için birim fiyat gerekli.")

    gross = quantity * price
    if txn_type == TXN_TYPE_SELL:
        if amount > 0 and abs(amount - gross) > 1e-6:
            raise WealthValidationError("Tutar miktar × birim fiyat ile uyuşmalı.")
        return gross

    if amount <= 0:
        return gross
    if abs(amount - gross) <= 1e-6:
        return gross
    if amount + 1e-6 < gross:
        raise WealthValidationError("Alış tutarı brüt maliyetten küçük olamaz.")
    return amount


def normalize_transfer_amount(
    *,
    quantity: float,
    price: Optional[float],
    amount: float,
) -> float:
    """Derive cost-basis amount for transfer rows (not cash economics)."""
    if quantity <= 0:
        raise WealthValidationError("Transfer miktarı sıfırdan büyük olmalı.")
    if price is None or price <= 0:
        raise WealthValidationError("Transfer için maliyet bazı (birim fiyat) gerekli.")
    computed = quantity * price
    if amount > 0 and abs(amount - computed) > 1e-6:
        raise WealthValidationError("Transfer tutarı miktar × maliyet ile uyuşmalı.")
    return computed
