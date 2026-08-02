alter table public.universe_symbols
    add column if not exists cik bigint;

create index if not exists idx_universe_symbols_cik
on public.universe_symbols(cik);

notify pgrst, 'reload schema';
