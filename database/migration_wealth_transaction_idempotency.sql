-- FUND27A — Wealth transaction idempotency foundation.
-- Additive and backward-compatible.
--
-- Purpose:
-- Prevent the same approved execution intent from being inserted into the
-- append-only wealth_transactions ledger more than once.
--
-- Existing/manual transactions may keep idempotency_key NULL.
-- Automated/controlled execution paths should provide a stable non-empty key.

alter table public.wealth_transactions
    add column if not exists idempotency_key text;

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_idempotency_key_not_blank;

alter table public.wealth_transactions
    add constraint wealth_transactions_idempotency_key_not_blank
    check (
        idempotency_key is null
        or length(btrim(idempotency_key)) > 0
    );

create unique index if not exists wealth_transactions_user_idempotency_uidx
    on public.wealth_transactions (user_id, idempotency_key)
    where idempotency_key is not null;

comment on column public.wealth_transactions.idempotency_key is
    'Stable caller-supplied execution key used to prevent duplicate ledger inserts.';
