from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from repositories.wealth_account_repository import WealthAccountRepository
from repositories.wealth_asset_repository import WealthAssetRepository
from repositories.wealth_liability_repository import WealthLiabilityRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from repositories.wealth_position_repository import WealthPositionRepository
from repositories.wealth_transaction_repository import WealthTransactionRepository
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    CASH_SYMBOL,
    TXN_TYPE_BUY,
    TXN_TYPE_CORPORATE_ACTION,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
    WealthMaterializationError,
    WealthValidationError,
    normalize_trade_amount,
    normalize_transfer_amount,
    validate_txn_type,
)
from services.wealth_position_engine import (
    materialize_position_from_transactions,
    validate_proposed_transaction,
)


@dataclass(frozen=True)
class WealthCoreSummary:
    portfolio_count: int
    account_count: int
    asset_count: int
    position_count: int
    liability_count: int
    transaction_count: int


class WealthCoreService:
    """Manual Wealth Core orchestration.

    Atomicity assumptions (Phase 1):
    - Business-rule validation replays the ledger with the proposed row before INSERT.
    - Transaction insert and position materialization run sequentially in app code.
    - There is no DB-level transaction wrapper; concurrent posts for the same
      account/asset may race. Position rebuild replays the full ledger on each
      post, so eventual consistency is restored on the next successful post.
    - wealth_transactions is append-only; corrections use reversal rows.
    """

    def __init__(self, client, user_id: str):
        self.client = client
        self.user_id = user_id
        self.portfolios = WealthPortfolioRepository(client)
        self.accounts = WealthAccountRepository(client)
        self.assets = WealthAssetRepository(client)
        self.liabilities = WealthLiabilityRepository(client)
        self.transactions = WealthTransactionRepository(client)
        self.positions = WealthPositionRepository(client)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_default_portfolio(self) -> Dict[str, Any]:
        existing = self.portfolios.get_default_for_user(self.user_id)
        if existing:
            return existing
        return self.portfolios.create(
            user_id=self.user_id,
            name="Ana Portföy",
            base_currency="USD",
            is_default=True,
        )

    def get_summary(self) -> WealthCoreSummary:
        portfolio_rows = self.portfolios.list_for_user(self.user_id)
        account_rows = self.accounts.list_for_user(self.user_id)
        asset_rows = self.assets.list_for_user(self.user_id)
        position_rows = self.positions.list_for_user(self.user_id)
        liability_rows = self.liabilities.list_for_user(self.user_id)
        txn_rows = self.transactions.list_for_user(self.user_id, limit=1000)
        return WealthCoreSummary(
            portfolio_count=len(portfolio_rows),
            account_count=len(account_rows),
            asset_count=len(asset_rows),
            position_count=len(position_rows),
            liability_count=len(liability_rows),
            transaction_count=len(txn_rows),
        )

    def create_account(
        self,
        *,
        name: str,
        account_type: str,
        currency: str = "USD",
        institution: Optional[str] = None,
        portfolio_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        portfolio = (
            self.portfolios.get_default_for_user(self.user_id)
            if not portfolio_id
            else next(
                (
                    row
                    for row in self.portfolios.list_for_user(self.user_id)
                    if row.get("id") == portfolio_id
                ),
                None,
            )
        )
        if portfolio is None:
            portfolio = self.ensure_default_portfolio()
        return self.accounts.create(
            user_id=self.user_id,
            portfolio_id=str(portfolio["id"]),
            name=name,
            account_type=account_type,
            currency=currency,
            institution=institution,
        )

    def register_asset(
        self,
        *,
        symbol: str,
        market: str,
        asset_class: str,
        currency: str = "USD",
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.assets.find_by_identity(
            self.user_id,
            symbol=symbol,
            market=market,
            asset_class=asset_class,
        )
        if existing:
            return existing
        return self.assets.create(
            user_id=self.user_id,
            symbol=symbol,
            market=market,
            asset_class=asset_class,
            currency=currency,
            name=name,
        )

    def ensure_cash_asset(self, currency: str) -> Dict[str, Any]:
        return self.register_asset(
            symbol=CASH_SYMBOL,
            market=currency.upper(),
            asset_class=ASSET_CLASS_CASH,
            currency=currency.upper(),
            name=f"Cash ({currency.upper()})",
        )

    def create_liability(
        self,
        *,
        name: str,
        liability_type: str,
        currency: str = "USD",
        principal: float = 0.0,
        portfolio_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if portfolio_id:
            owned = any(
                row.get("id") == portfolio_id
                for row in self.portfolios.list_for_user(self.user_id)
            )
            if not owned:
                raise WealthValidationError("Portföy bulunamadı.")
        return self.liabilities.create(
            user_id=self.user_id,
            name=name,
            liability_type=liability_type,
            currency=currency,
            principal=principal,
            portfolio_id=portfolio_id,
            notes=notes,
        )

    def _validate_transaction_payload(
        self,
        *,
        account_id: str,
        asset_id: Optional[str],
        txn_type: str,
        quantity: float,
        amount: float,
        price: Optional[float],
    ) -> str:
        normalized_type = validate_txn_type(txn_type)
        account = self.accounts.get_by_id(self.user_id, account_id)
        if account is None:
            raise WealthValidationError("Hesap bulunamadı.")

        if normalized_type in {
            TXN_TYPE_BUY,
            TXN_TYPE_SELL,
            TXN_TYPE_DIVIDEND,
            TXN_TYPE_DEPOSIT,
            TXN_TYPE_WITHDRAW,
            TXN_TYPE_FEE,
            TXN_TYPE_TRANSFER_OUT,
            TXN_TYPE_TRANSFER_IN,
            TXN_TYPE_CORPORATE_ACTION,
        } and not asset_id:
            raise WealthValidationError("Bu işlem türü için varlık gerekli.")

        if asset_id:
            asset = self.assets.get_by_id(self.user_id, asset_id)
            if asset is None:
                raise WealthValidationError("Varlık bulunamadı.")

        if quantity < 0:
            raise WealthValidationError("Miktar negatif olamaz.")
        if amount < 0:
            raise WealthValidationError("Tutar negatif olamaz.")

        if normalized_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            if quantity <= 0:
                raise WealthValidationError("Alış/satış için miktar sıfırdan büyük olmalı.")
            if price is None or price <= 0:
                raise WealthValidationError("Alış/satış için birim fiyat gerekli.")

        if normalized_type in {TXN_TYPE_TRANSFER_OUT, TXN_TYPE_TRANSFER_IN}:
            if quantity <= 0:
                raise WealthValidationError("Transfer için miktar sıfırdan büyük olmalı.")
            if price is None or price <= 0:
                raise WealthValidationError("Transfer için maliyet bazı (birim fiyat) gerekli.")

        if normalized_type in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW, TXN_TYPE_FEE}:
            if quantity <= 0 and amount <= 0:
                raise WealthValidationError("Nakit işlemlerde miktar veya tutar gerekli.")

        if normalized_type == TXN_TYPE_CORPORATE_ACTION:
            if quantity <= 0:
                raise WealthValidationError("Kurumsal işlemde miktar sıfırdan büyük olmalı.")
            if abs(float(amount or 0.0)) > 1e-9:
                raise WealthValidationError("Kurumsal işlem nakit maliyeti oluşturmaz.")

        return normalized_type

    def _validate_reversal_before_insert(
        self,
        *,
        account_id: str,
        asset_id: Optional[str],
        reversal_of_id: str,
        txn_type: str,
        quantity: float,
        amount: float,
    ) -> Dict[str, Any]:
        original = self.transactions.get_by_id(self.user_id, reversal_of_id)
        if original is None:
            raise WealthValidationError("Ters kayıt için kaynak işlem bulunamadı.")
        if original.get("account_id") != account_id:
            raise WealthValidationError("Ters kayıt hesabı kaynak işlemle eşleşmiyor.")
        if original.get("asset_id") != asset_id:
            raise WealthValidationError("Ters kayıt varlığı kaynak işlemle eşleşmiyor.")
        if self.transactions.has_reversal_for(self.user_id, reversal_of_id):
            raise WealthValidationError("Bu işlem zaten ters kayıt ile düzeltilmiş.")
        if str(original.get("txn_type") or "").strip().lower() != txn_type:
            raise WealthValidationError("Ters kayıt türü kaynak işlemle eşleşmeli.")
        if float(original.get("quantity") or 0) != quantity:
            raise WealthValidationError("Ters kayıt miktarı kaynak işlemle eşleşmeli.")
        if abs(float(original.get("amount") or 0) - amount) > 1e-6:
            raise WealthValidationError("Ters kayıt tutarı kaynak işlemle eşleşmeli.")
        return original

    def _validate_ledger_acceptance(
        self,
        *,
        account_id: str,
        asset_id: str,
        proposed_row: Dict[str, Any],
    ) -> None:
        ledger_rows = self.transactions.list_for_position(
            self.user_id,
            account_id,
            asset_id,
        )
        validate_proposed_transaction(ledger_rows, proposed_row)

    def _rebuild_position(self, account_id: str, asset_id: str, cost_currency: str) -> None:
        ledger_rows = self.transactions.list_for_position(
            self.user_id,
            account_id,
            asset_id,
        )
        quantity, average_cost = materialize_position_from_transactions(ledger_rows)
        if quantity == 0:
            self.positions.delete_for_account_asset(self.user_id, account_id, asset_id)
            return
        self.positions.upsert(
            user_id=self.user_id,
            account_id=account_id,
            asset_id=asset_id,
            quantity=quantity,
            average_cost=average_cost,
            cost_currency=cost_currency,
        )

    def post_transaction(
        self,
        *,
        account_id: str,
        txn_type: str,
        quantity: float,
        amount: float,
        currency: str = "USD",
        asset_id: Optional[str] = None,
        price: Optional[float] = None,
        executed_at: Optional[str] = None,
        notes: Optional[str] = None,
        reversal_of_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = self._validate_transaction_payload(
            account_id=account_id,
            asset_id=asset_id,
            txn_type=txn_type,
            quantity=quantity,
            amount=amount,
            price=price,
        )

        normalized_amount = normalize_trade_amount(
            normalized_type,
            quantity=quantity,
            price=price,
            amount=amount,
        )
        if normalized_type in {TXN_TYPE_TRANSFER_OUT, TXN_TYPE_TRANSFER_IN}:
            normalized_amount = normalize_transfer_amount(
                quantity=quantity,
                price=price,
                amount=amount,
            )

        if reversal_of_id:
            self._validate_reversal_before_insert(
                account_id=account_id,
                asset_id=asset_id,
                reversal_of_id=reversal_of_id,
                txn_type=normalized_type,
                quantity=quantity,
                amount=normalized_amount,
            )

        account = self.accounts.get_by_id(self.user_id, account_id)
        if account is None:
            raise WealthValidationError("Hesap bulunamadı.")

        asset = self.assets.get_by_id(self.user_id, str(asset_id)) if asset_id else None
        cost_currency = str((asset or {}).get("currency") or account.get("currency") or currency)
        executed_value = executed_at or self._now_iso()

        proposed_row = {
            "txn_type": normalized_type,
            "quantity": quantity,
            "price": price,
            "amount": normalized_amount,
            "executed_at": executed_value,
            "reversal_of_id": reversal_of_id,
        }

        if asset_id:
            self._validate_ledger_acceptance(
                account_id=account_id,
                asset_id=asset_id,
                proposed_row=proposed_row,
            )

        payload = {
            "user_id": self.user_id,
            "account_id": account_id,
            "asset_id": asset_id,
            "txn_type": normalized_type,
            "quantity": quantity,
            "price": price,
            "amount": normalized_amount,
            "currency": currency.strip().upper(),
            "executed_at": executed_value,
            "notes": notes.strip() if notes else None,
            "reversal_of_id": reversal_of_id,
        }
        inserted = self.transactions.insert(payload)

        if asset_id:
            try:
                self._rebuild_position(account_id, asset_id, cost_currency)
            except Exception as exc:
                raise WealthMaterializationError(
                    "İşlem deftere yazıldı ancak pozisyon güncellenemedi. "
                    "Sonraki başarılı işlem veya yeniden oynatma ile düzelecektir."
                ) from exc

        return inserted

    def post_transfer(
        self,
        *,
        from_account_id: str,
        to_account_id: str,
        asset_id: str,
        quantity: float,
        price: float,
        currency: str = "USD",
        executed_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Account-to-account asset transfer preserving cost basis (no fake buy/sell)."""
        if from_account_id == to_account_id:
            raise WealthValidationError("Kaynak ve hedef hesap aynı olamaz.")
        if quantity <= 0:
            raise WealthValidationError("Transfer miktarı sıfırdan büyük olmalı.")
        if price <= 0:
            raise WealthValidationError("Transfer için maliyet bazı gerekli.")

        source_account = self.accounts.get_by_id(self.user_id, from_account_id)
        dest_account = self.accounts.get_by_id(self.user_id, to_account_id)
        if source_account is None or dest_account is None:
            raise WealthValidationError("Kaynak veya hedef hesap bulunamadı.")

        asset = self.assets.get_by_id(self.user_id, asset_id)
        if asset is None:
            raise WealthValidationError("Varlık bulunamadı.")

        amount = normalize_transfer_amount(
            quantity=quantity,
            price=price,
            amount=quantity * price,
        )
        cost_currency = str(asset.get("currency") or source_account.get("currency") or currency)
        executed_value = executed_at or self._now_iso()
        transfer_link_id = str(uuid.uuid4())
        transfer_note = notes.strip() if notes else "Kurumlar arası transfer"

        out_proposed = {
            "txn_type": TXN_TYPE_TRANSFER_OUT,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "executed_at": executed_value,
        }
        self._validate_ledger_acceptance(
            account_id=from_account_id,
            asset_id=asset_id,
            proposed_row=out_proposed,
        )

        in_proposed = {
            "txn_type": TXN_TYPE_TRANSFER_IN,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "executed_at": executed_value,
        }
        self._validate_ledger_acceptance(
            account_id=to_account_id,
            asset_id=asset_id,
            proposed_row=in_proposed,
        )

        out_payload = {
            "user_id": self.user_id,
            "account_id": from_account_id,
            "asset_id": asset_id,
            "txn_type": TXN_TYPE_TRANSFER_OUT,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "currency": currency.strip().upper(),
            "executed_at": executed_value,
            "notes": f"{transfer_note} — çıkış",
            "transfer_link_id": transfer_link_id,
            "counterparty_account_id": to_account_id,
        }
        in_payload = {
            "user_id": self.user_id,
            "account_id": to_account_id,
            "asset_id": asset_id,
            "txn_type": TXN_TYPE_TRANSFER_IN,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "currency": currency.strip().upper(),
            "executed_at": executed_value,
            "notes": f"{transfer_note} — giriş",
            "transfer_link_id": transfer_link_id,
            "counterparty_account_id": from_account_id,
        }

        self.transactions.insert(out_payload)
        inserted_in = self.transactions.insert(in_payload)

        try:
            self._rebuild_position(from_account_id, asset_id, cost_currency)
            self._rebuild_position(to_account_id, asset_id, cost_currency)
        except Exception as exc:
            raise WealthMaterializationError(
                "Transfer deftere yazıldı ancak pozisyon güncellenemedi."
            ) from exc

        return inserted_in

    def deactivate_account(self, account_id: str) -> Dict[str, Any]:
        account = self.accounts.get_by_id(self.user_id, account_id)
        if account is None:
            raise WealthValidationError("Hesap bulunamadı.")
        open_positions = [
            row
            for row in self.list_positions()
            if str(row.get("account_id") or "") == str(account_id)
        ]
        if open_positions:
            raise WealthValidationError(
                "Açık pozisyonu olan hesap pasifleştirilemez."
            )
        txns = [
            row
            for row in self.list_transactions(limit=1000)
            if str(row.get("account_id") or "") == str(account_id)
        ]
        if txns:
            raise WealthValidationError(
                "İşlem geçmişi olan hesap pasifleştirilemez."
            )
        updated = self.accounts.update_active(self.user_id, account_id, is_active=False)
        if updated is None:
            raise WealthValidationError("Hesap güncellenemedi.")
        return updated

    def list_positions(self) -> List[Dict[str, Any]]:
        return self.positions.list_for_user(self.user_id)

    def list_accounts(self) -> List[Dict[str, Any]]:
        return self.accounts.list_for_user(self.user_id)

    def list_assets(self) -> List[Dict[str, Any]]:
        return self.assets.list_for_user(self.user_id)

    def list_liabilities(self) -> List[Dict[str, Any]]:
        return self.liabilities.list_for_user(self.user_id)

    def list_transactions(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        return self.transactions.list_for_user(self.user_id, limit=limit)

    @staticmethod
    def collect_reversed_original_ids(transactions: Iterable[Dict[str, Any]]) -> set[str]:
        from services.wealth_position_engine import _collect_reversed_original_ids

        return _collect_reversed_original_ids(transactions)

    @staticmethod
    def is_transaction_reversal_eligible(
        txn: Dict[str, Any],
        reversed_original_ids: set[str],
    ) -> bool:
        if txn.get("reversal_of_id"):
            return False
        txn_id = str(txn.get("id") or "")
        if not txn_id:
            return False
        return txn_id not in reversed_original_ids

    @staticmethod
    def _price_from_original(original: Dict[str, Any]) -> Optional[float]:
        price = original.get("price")
        if price is not None and float(price) > 0:
            return float(price)
        quantity = float(original.get("quantity") or 0.0)
        amount = float(original.get("amount") or 0.0)
        if quantity > 0 and amount > 0:
            return amount / quantity
        return None

    def reverse_transaction(self, original_txn_id: str) -> Dict[str, Any]:
        original = self.transactions.get_by_id(self.user_id, original_txn_id)
        if original is None:
            raise WealthValidationError("İşlem bulunamadı.")
        if original.get("reversal_of_id"):
            raise WealthValidationError("Ters kayıt satırı geri alınamaz.")

        recent = self.transactions.list_for_user(self.user_id, limit=1000)
        reversed_ids = self.collect_reversed_original_ids(recent)
        if not self.is_transaction_reversal_eligible(original, reversed_ids):
            raise WealthValidationError("Bu işlem zaten geri alınmış.")

        asset_id = original.get("asset_id")
        price = self._price_from_original(original)
        return self.post_transaction(
            account_id=str(original["account_id"]),
            asset_id=str(asset_id) if asset_id else None,
            txn_type=str(original["txn_type"]),
            quantity=float(original["quantity"]),
            amount=float(original["amount"]),
            currency=str(original.get("currency") or "USD"),
            price=price,
            notes="İşlem geri alma kaydı",
            reversal_of_id=str(original_txn_id),
        )
