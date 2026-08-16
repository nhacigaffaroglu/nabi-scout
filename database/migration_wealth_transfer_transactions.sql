-- Wealth OS — account-to-account asset transfers (additive, idempotent).
-- Adds transfer_out / transfer_in ledger types without fake buy/sell economics.

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
            'transfer_in'
        )
    );

alter table public.wealth_transactions
    add column if not exists transfer_link_id uuid;

create index if not exists wealth_transactions_transfer_link_idx
    on public.wealth_transactions (user_id, transfer_link_id)
    where transfer_link_id is not null;

-- Optional paired-account audit (same user scope enforced in app layer).
alter table public.wealth_transactions
    add column if not exists counterparty_account_id uuid;

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_counterparty_account_owner_fkey;

alter table public.wealth_transactions
    add constraint wealth_transactions_counterparty_account_owner_fkey
    foreign key (user_id, counterparty_account_id)
    references public.wealth_accounts (user_id, id)
    on delete restrict;
