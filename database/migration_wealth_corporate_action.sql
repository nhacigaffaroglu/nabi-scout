-- Wealth OS — generic stock-split / bonus-share ledger type.
-- Additive, idempotent. Does not rewrite existing rows.

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_txn_type_check;

alter table public.wealth_transactions
    add constraint wealth_transactions_txn_type_check
    check (
        txn_type in (
            'buy',
            'sell',
            'dividend',
            'deposit',
            'withdraw',
            'fee',
            'transfer_out',
            'transfer_in',
            'corporate_action'
        )
    );
