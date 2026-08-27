-- Security Master v1 — auditable instrument facts, not economic-exposure policy.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.
-- Identity is (identifier, identifier_type, source). Ticker is not globally unique.

create table if not exists public.security_master (
    id uuid primary key default gen_random_uuid(),
    identifier text not null,
    identifier_type text not null,
    instrument_type text not null,
    source text not null,
    observed_at timestamptz not null,
    symbol text,
    exchange text,
    issuer_name text,
    source_reference text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint security_master_identifier_type_chk
        check (identifier_type in ('TICKER', 'CUSIP', 'SEDOL', 'ISIN')),
    constraint security_master_instrument_type_chk
        check (instrument_type in (
            'EQUITY',
            'REIT',
            'SUKUK',
            'FIXED_INCOME',
            'CASH',
            'ETF',
            'COMMODITY',
            'OTHER',
            'UNKNOWN'
        )),
    constraint security_master_identity_uidx
        unique (identifier, identifier_type, source)
);

create index if not exists security_master_identifier_idx
    on public.security_master (identifier, identifier_type);

create index if not exists security_master_source_idx
    on public.security_master (source, observed_at desc);

alter table public.security_master enable row level security;

drop policy if exists "authenticated security master read"
    on public.security_master;
create policy "authenticated security master read"
on public.security_master
for select
to authenticated
using (true);

drop policy if exists "service role security master write"
    on public.security_master;
create policy "service role security master write"
on public.security_master
for all
to service_role
using (true)
with check (true);

notify pgrst, 'reload schema';
