from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_OTHER,
    ACCOUNT_TYPE_BROKERAGE,
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_WITHDRAW,
    WealthValidationError,
    normalize_symbol,
)
from services.wealth_core_service import WealthCoreService


ASSET_CLASS_OPTIONS = (
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_CASH,
    ASSET_CLASS_OTHER,
)


def _parse_executed_at(value: Optional[str]) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc).isoformat()
    if len(text) == 10:
        try:
            parsed = date.fromisoformat(text)
            return datetime(
                parsed.year,
                parsed.month,
                parsed.day,
                tzinfo=timezone.utc,
            ).isoformat()
        except ValueError as exc:
            raise WealthValidationError("Geçersiz alış tarihi.") from exc
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WealthValidationError("Geçersiz alış tarihi.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _find_open_position(
    wealth: WealthCoreService,
    *,
    account_id: str,
    asset_id: str,
) -> Optional[Dict[str, Any]]:
    for row in wealth.list_positions():
        if (
            str(row.get("account_id") or "") == str(account_id)
            and str(row.get("asset_id") or "") == str(asset_id)
        ):
            return row
    return None


class PortfolioManagementService:
    """Accounting-safe portfolio writes via Wealth Core ledger."""

    def __init__(self, wealth: WealthCoreService) -> None:
        self.wealth = wealth

    def create_institution_account(
        self,
        *,
        institution: str,
        account_label: str,
        currency: str = "USD",
        portfolio_id: Optional[str] = None,
        account_type: str = ACCOUNT_TYPE_BROKERAGE,
    ) -> Dict[str, Any]:
        institution_text = str(institution or "").strip()
        label_text = str(account_label or "").strip()
        if not institution_text:
            raise WealthValidationError("Kurum adı gerekli.")
        if not label_text:
            raise WealthValidationError("Hesap etiketi gerekli.")
        return self.wealth.create_account(
            name=label_text,
            account_type=account_type,
            currency=currency.strip().upper(),
            institution=institution_text,
            portfolio_id=portfolio_id,
        )

    def add_holding(
        self,
        *,
        account_id: str,
        symbol: str,
        quantity: float,
        average_cost: float,
        currency: str = "USD",
        asset_class: str = ASSET_CLASS_EQUITY,
        market: str = "US",
        executed_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not str(account_id or "").strip():
            raise WealthValidationError("Kurum / hesap seçimi gerekli.")
        sym = normalize_symbol(symbol)
        if not sym:
            raise WealthValidationError("Sembol gerekli.")
        if quantity <= 0:
            raise WealthValidationError("Adet sıfırdan büyük olmalı.")
        if average_cost < 0:
            raise WealthValidationError("Alış fiyatı negatif olamaz.")

        normalized_class = str(asset_class or ASSET_CLASS_EQUITY).strip().lower()
        if normalized_class not in ASSET_CLASS_OPTIONS:
            raise WealthValidationError(f"Desteklenmeyen varlık sınıfı: {asset_class}")

        if normalized_class == ASSET_CLASS_CASH:
            asset = self.wealth.ensure_cash_asset(currency.strip().upper())

            return self.wealth.post_transaction(
                account_id=account_id,
                txn_type=TXN_TYPE_DEPOSIT,
                quantity=quantity,
                amount=quantity,
                currency=currency.strip().upper(),
                asset_id=str(asset["id"]),
                price=1.0,
                executed_at=_parse_executed_at(executed_at),
                notes=notes or "Portföye ekle — nakit",
            )

        asset = self.wealth.register_asset(
            symbol=sym,
            market=str(market or "US").strip().upper(),
            asset_class=normalized_class,
            currency=currency.strip().upper(),
        )
        amount = quantity * average_cost
        return self.wealth.post_transaction(
            account_id=account_id,
            txn_type=TXN_TYPE_BUY,
            quantity=quantity,
            amount=amount,
            currency=currency.strip().upper(),
            asset_id=str(asset["id"]),
            price=average_cost,
            executed_at=_parse_executed_at(executed_at),
            notes=notes or "Portföye ekle",
        )

    def close_holding(
        self,
        *,
        account_id: str,
        asset_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        position = _find_open_position(
            self.wealth,
            account_id=account_id,
            asset_id=asset_id,
        )
        if position is None:
            raise WealthValidationError("Kapatılacak açık pozisyon bulunamadı.")
        quantity = float(position.get("quantity") or 0.0)
        if quantity <= 0:
            raise WealthValidationError("Pozisyon zaten kapalı.")
        average_cost = float(position.get("average_cost") or 0.0)
        asset = self.wealth.assets.get_by_id(self.wealth.user_id, asset_id)
        currency = str(
            (asset or {}).get("currency")
            or position.get("cost_currency")
            or "USD"
        )
        return self.wealth.post_transaction(
            account_id=account_id,
            txn_type=TXN_TYPE_SELL,
            quantity=quantity,
            amount=quantity * average_cost,
            currency=currency,
            asset_id=asset_id,
            price=average_cost,
            notes=notes or "Pozisyon kapatma",
        )

    def adjust_holding(
        self,
        *,
        account_id: str,
        asset_id: str,
        new_quantity: float,
        new_average_cost: float,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if new_quantity < 0:
            raise WealthValidationError("Adet negatif olamaz.")
        if new_average_cost < 0:
            raise WealthValidationError("Ortalama maliyet negatif olamaz.")

        position = _find_open_position(
            self.wealth,
            account_id=account_id,
            asset_id=asset_id,
        )
        if position is None and new_quantity <= 0:
            return {"status": "noop"}
        if position is None:
            asset = self.wealth.assets.get_by_id(self.wealth.user_id, asset_id)
            if asset is None:
                raise WealthValidationError("Varlık bulunamadı.")
            return self.add_holding(
                account_id=account_id,
                symbol=str(asset.get("symbol") or ""),
                quantity=new_quantity,
                average_cost=new_average_cost,
                currency=str(asset.get("currency") or "USD"),
                asset_class=str(asset.get("asset_class") or ASSET_CLASS_EQUITY),
                market=str(asset.get("market") or "US"),
                notes=notes or "Pozisyon düzeltme",
            )

        current_qty = float(position.get("quantity") or 0.0)
        current_cost = float(position.get("average_cost") or 0.0)
        if (
            abs(current_qty - new_quantity) < 1e-9
            and abs(current_cost - new_average_cost) < 1e-9
        ):
            return {"status": "noop", "position_id": position.get("id")}

        asset = self.wealth.assets.get_by_id(self.wealth.user_id, asset_id)
        if asset is None:
            raise WealthValidationError("Varlık bulunamadı.")

        if new_quantity == 0:
            return self.close_holding(
                account_id=account_id,
                asset_id=asset_id,
                notes=notes or "Pozisyon düzeltme — kapatma",
            )

        self.close_holding(
            account_id=account_id,
            asset_id=asset_id,
            notes=notes or "Pozisyon düzeltme — yeniden açılış öncesi kapatma",
        )
        return self.add_holding(
            account_id=account_id,
            symbol=str(asset.get("symbol") or ""),
            quantity=new_quantity,
            average_cost=new_average_cost,
            currency=str(asset.get("currency") or "USD"),
            asset_class=str(asset.get("asset_class") or ASSET_CLASS_EQUITY),
            market=str(asset.get("market") or "US"),
            notes=notes or "Pozisyon düzeltme — yeni maliyet",
        )

    def transfer_holding(
        self,
        *,
        from_account_id: str,
        to_account_id: str,
        asset_id: str,
        quantity: float,
        executed_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if from_account_id == to_account_id:
            raise WealthValidationError("Kaynak ve hedef hesap aynı olamaz.")
        if quantity <= 0:
            raise WealthValidationError("Transfer miktarı sıfırdan büyük olmalı.")

        source = _find_open_position(
            self.wealth,
            account_id=from_account_id,
            asset_id=asset_id,
        )
        if source is None:
            raise WealthValidationError("Kaynak hesapta pozisyon bulunamadı.")
        available = float(source.get("quantity") or 0.0)
        if quantity > available + 1e-9:
            raise WealthValidationError("Transfer miktarı mevcut pozisyonu aşıyor.")

        average_cost = float(source.get("average_cost") or 0.0)
        asset = self.wealth.assets.get_by_id(self.wealth.user_id, asset_id)
        if asset is None:
            raise WealthValidationError("Varlık bulunamadı.")
        currency = str(asset.get("currency") or "USD")

        return self.wealth.post_transfer(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            asset_id=asset_id,
            quantity=quantity,
            price=average_cost,
            currency=currency,
            executed_at=_parse_executed_at(executed_at) if executed_at else None,
            notes=notes or "Kurumlar arası transfer",
        )

    def deactivate_empty_account(self, account_id: str) -> Dict[str, Any]:
        return self.wealth.deactivate_account(account_id)

    def record_cash_event(
        self,
        *,
        account_id: str,
        txn_type: str,
        amount: float,
        currency: str = "USD",
        symbol: Optional[str] = None,
        executed_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = str(txn_type or "").strip().lower()
        if normalized not in {
            TXN_TYPE_DIVIDEND,
            TXN_TYPE_FEE,
            TXN_TYPE_DEPOSIT,
            TXN_TYPE_WITHDRAW,
        }:
            raise WealthValidationError("Desteklenmeyen nakit işlem türü.")
        if amount <= 0:
            raise WealthValidationError("Tutar sıfırdan büyük olmalı.")

        asset = None
        if normalized == TXN_TYPE_DIVIDEND and symbol:
            sym = normalize_symbol(symbol)
            asset = self.wealth.register_asset(
                symbol=sym,
                market="US",
                asset_class=ASSET_CLASS_EQUITY,
                currency=currency.strip().upper(),
            )
        elif normalized in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW, TXN_TYPE_FEE}:
            asset = self.wealth.ensure_cash_asset(currency.strip().upper())

        return self.wealth.post_transaction(
            account_id=account_id,
            txn_type=normalized,
            quantity=amount if normalized == TXN_TYPE_DIVIDEND else 0.0,
            amount=amount,
            currency=currency.strip().upper(),
            asset_id=str(asset["id"]) if asset else None,
            price=1.0 if asset else None,
            executed_at=_parse_executed_at(executed_at) if executed_at else None,
            notes=notes,
        )
