alter table public.universe_symbols
    add column if not exists cik bigint;

create index if not exists idx_universe_symbols_name_cik
on public.universe_symbols(universe_name, cik);

notify pgrst, 'reload schema';
