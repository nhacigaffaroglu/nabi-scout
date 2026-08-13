-- Wealth OS Phase 1 — manual Wealth Core (additive, idempotent).
-- Personal wealth data is user-scoped with auth.uid() RLS.
-- wealth_transactions is the append-only ledger; wealth_positions is materialized state.

create table if not exists public.wealth_portfolios (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    base_currency text not null default 'USD',
    is_default boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists wealth_portfolios_one_default_per_user_idx
    on public.wealth_portfolios (user_id)
    where is_default = true;

create table if not exists public.wealth_accounts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null references public.wealth_portfolios(id) on delete cascade,
    name text not null,
    account_type text not null,
    currency text not null default 'USD',
    institution text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists wealth_accounts_user_portfolio_idx
    on public.wealth_accounts (user_id, portfolio_id);

create table if not exists public.wealth_assets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    symbol text not null,
    market text not null default 'US',
    asset_class text not null,
    name text,
    currency text not null default 'USD',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, symbol, market, asset_class)
);

create index if not exists wealth_assets_user_symbol_idx
    on public.wealth_assets (user_id, symbol);

create table if not exists public.wealth_liabilities (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid references public.wealth_portfolios(id) on delete set null,
    name text not null,
    liability_type text not null,
    currency text not null default 'USD',
    principal numeric not null default 0,
    interest_rate numeric,
    maturity_date date,
    notes text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists wealth_liabilities_user_portfolio_idx
    on public.wealth_liabilities (user_id, portfolio_id);

create table if not exists public.wealth_transactions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    account_id uuid not null references public.wealth_accounts(id) on delete restrict,
    asset_id uuid references public.wealth_assets(id) on delete restrict,
    txn_type text not null,
    quantity numeric not null check (quantity >= 0),
    price numeric,
    amount numeric not null,
    currency text not null default 'USD',
    executed_at timestamptz not null default now(),
    notes text,
    reversal_of_id uuid references public.wealth_transactions(id) on delete restrict,
    created_at timestamptz not null default now(),
    check (txn_type in ('buy', 'sell', 'dividend', 'deposit', 'withdraw', 'fee'))
);

create index if not exists wealth_transactions_user_account_asset_idx
    on public.wealth_transactions (user_id, account_id, asset_id, executed_at, created_at);

create table if not exists public.wealth_positions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    account_id uuid not null references public.wealth_accounts(id) on delete cascade,
    asset_id uuid not null references public.wealth_assets(id) on delete cascade,
    quantity numeric not null default 0,
    average_cost numeric not null default 0,
    cost_currency text not null default 'USD',
    updated_at timestamptz not null default now(),
    unique (user_id, account_id, asset_id)
);

create index if not exists wealth_positions_user_account_idx
    on public.wealth_positions (user_id, account_id);

-- Composite (user_id, id) keys enable ownership-safe child foreign keys.
create unique index if not exists wealth_portfolios_user_id_id_uidx
    on public.wealth_portfolios (user_id, id);

create unique index if not exists wealth_accounts_user_id_id_uidx
    on public.wealth_accounts (user_id, id);

create unique index if not exists wealth_assets_user_id_id_uidx
    on public.wealth_assets (user_id, id);

create unique index if not exists wealth_transactions_user_id_id_uidx
    on public.wealth_transactions (user_id, id);

-- Replace single-column FKs with co-ownership FKs so a row cannot reference
-- another user's portfolio/account/asset while using its own user_id.
alter table public.wealth_accounts
    drop constraint if exists wealth_accounts_portfolio_id_fkey;
alter table public.wealth_accounts
    drop constraint if exists wealth_accounts_portfolio_owner_fkey;
alter table public.wealth_accounts
    add constraint wealth_accounts_portfolio_owner_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

alter table public.wealth_liabilities
    drop constraint if exists wealth_liabilities_portfolio_id_fkey;
alter table public.wealth_liabilities
    drop constraint if exists wealth_liabilities_portfolio_owner_fkey;
alter table public.wealth_liabilities
    add constraint wealth_liabilities_portfolio_owner_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete set null;

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_account_id_fkey;
alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_account_owner_fkey;
alter table public.wealth_transactions
    add constraint wealth_transactions_account_owner_fkey
    foreign key (user_id, account_id)
    references public.wealth_accounts (user_id, id)
    on delete restrict;

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_asset_id_fkey;
alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_asset_owner_fkey;
alter table public.wealth_transactions
    add constraint wealth_transactions_asset_owner_fkey
    foreign key (user_id, asset_id)
    references public.wealth_assets (user_id, id)
    on delete restrict;

alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_reversal_of_id_fkey;
alter table public.wealth_transactions
    drop constraint if exists wealth_transactions_reversal_owner_fkey;
alter table public.wealth_transactions
    add constraint wealth_transactions_reversal_owner_fkey
    foreign key (user_id, reversal_of_id)
    references public.wealth_transactions (user_id, id)
    on delete restrict;

alter table public.wealth_positions
    drop constraint if exists wealth_positions_account_id_fkey;
alter table public.wealth_positions
    drop constraint if exists wealth_positions_account_owner_fkey;
alter table public.wealth_positions
    add constraint wealth_positions_account_owner_fkey
    foreign key (user_id, account_id)
    references public.wealth_accounts (user_id, id)
    on delete cascade;

alter table public.wealth_positions
    drop constraint if exists wealth_positions_asset_id_fkey;
alter table public.wealth_positions
    drop constraint if exists wealth_positions_asset_owner_fkey;
alter table public.wealth_positions
    add constraint wealth_positions_asset_owner_fkey
    foreign key (user_id, asset_id)
    references public.wealth_assets (user_id, id)
    on delete cascade;

alter table public.wealth_portfolios enable row level security;
alter table public.wealth_accounts enable row level security;
alter table public.wealth_assets enable row level security;
alter table public.wealth_liabilities enable row level security;
alter table public.wealth_transactions enable row level security;
alter table public.wealth_positions enable row level security;

-- Portfolios
drop policy if exists "wealth portfolios select own" on public.wealth_portfolios;
create policy "wealth portfolios select own"
on public.wealth_portfolios for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth portfolios insert own" on public.wealth_portfolios;
create policy "wealth portfolios insert own"
on public.wealth_portfolios for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth portfolios update own" on public.wealth_portfolios;
create policy "wealth portfolios update own"
on public.wealth_portfolios for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth portfolios delete own" on public.wealth_portfolios;
create policy "wealth portfolios delete own"
on public.wealth_portfolios for delete to authenticated
using (auth.uid() = user_id);

-- Accounts
drop policy if exists "wealth accounts select own" on public.wealth_accounts;
create policy "wealth accounts select own"
on public.wealth_accounts for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth accounts insert own" on public.wealth_accounts;
create policy "wealth accounts insert own"
on public.wealth_accounts for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth accounts update own" on public.wealth_accounts;
create policy "wealth accounts update own"
on public.wealth_accounts for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth accounts delete own" on public.wealth_accounts;
create policy "wealth accounts delete own"
on public.wealth_accounts for delete to authenticated
using (auth.uid() = user_id);

-- Assets
drop policy if exists "wealth assets select own" on public.wealth_assets;
create policy "wealth assets select own"
on public.wealth_assets for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth assets insert own" on public.wealth_assets;
create policy "wealth assets insert own"
on public.wealth_assets for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth assets update own" on public.wealth_assets;
create policy "wealth assets update own"
on public.wealth_assets for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth assets delete own" on public.wealth_assets;
create policy "wealth assets delete own"
on public.wealth_assets for delete to authenticated
using (auth.uid() = user_id);

-- Liabilities
drop policy if exists "wealth liabilities select own" on public.wealth_liabilities;
create policy "wealth liabilities select own"
on public.wealth_liabilities for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth liabilities insert own" on public.wealth_liabilities;
create policy "wealth liabilities insert own"
on public.wealth_liabilities for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth liabilities update own" on public.wealth_liabilities;
create policy "wealth liabilities update own"
on public.wealth_liabilities for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth liabilities delete own" on public.wealth_liabilities;
create policy "wealth liabilities delete own"
on public.wealth_liabilities for delete to authenticated
using (auth.uid() = user_id);

-- Transactions (append-only: select + insert only)
drop policy if exists "wealth transactions select own" on public.wealth_transactions;
create policy "wealth transactions select own"
on public.wealth_transactions for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth transactions insert own" on public.wealth_transactions;
create policy "wealth transactions insert own"
on public.wealth_transactions for insert to authenticated
with check (auth.uid() = user_id);

-- Positions (materialized by app service)
drop policy if exists "wealth positions select own" on public.wealth_positions;
create policy "wealth positions select own"
on public.wealth_positions for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth positions insert own" on public.wealth_positions;
create policy "wealth positions insert own"
on public.wealth_positions for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth positions update own" on public.wealth_positions;
create policy "wealth positions update own"
on public.wealth_positions for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth positions delete own" on public.wealth_positions;
create policy "wealth positions delete own"
on public.wealth_positions for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
