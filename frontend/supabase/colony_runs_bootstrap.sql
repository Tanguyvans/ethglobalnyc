-- WorldColony — incremental bootstrap for benchmark colony run history.
-- Use this if public.colonies already exists and the app errors with:
-- "Could not find the table 'public.colony_runs' in the schema cache".

create extension if not exists pgcrypto;

create table if not exists public.colony_runs (
  id              uuid primary key default gen_random_uuid(),
  pubkey          text not null references public.colonies(pubkey) on delete cascade,
  run_id          text,
  status          text not null default 'queued',
  config_snapshot jsonb not null default '{}'::jsonb,
  code_version    text,
  artifacts       jsonb not null default '{}'::jsonb,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint colony_runs_status_check
    check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  constraint colony_runs_config_snapshot_is_object_check
    check (jsonb_typeof(config_snapshot) = 'object'),
  constraint colony_runs_artifacts_is_object_check
    check (jsonb_typeof(artifacts) = 'object')
);

alter table public.colony_runs
  add column if not exists started_at timestamptz,
  add column if not exists completed_at timestamptz;

create index if not exists colony_runs_pubkey_created_at_idx
  on public.colony_runs (pubkey, created_at desc);

create index if not exists colony_runs_run_id_idx
  on public.colony_runs (run_id);

create unique index if not exists colony_runs_run_id_unique_idx
  on public.colony_runs (run_id)
  where run_id is not null;

create or replace function public.colony_runs_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists colony_runs_touch_updated_at on public.colony_runs;
create trigger colony_runs_touch_updated_at
  before update on public.colony_runs
  for each row execute function public.colony_runs_touch_updated_at();

alter table public.colony_runs enable row level security;

-- No public policies: benchmark runs are written/read by the backend service
-- role, then exposed through the sanitized /benchmark/runs endpoint.

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'colony_runs'
  ) then
    alter publication supabase_realtime add table public.colony_runs;
  end if;
end $$;

notify pgrst, 'reload schema';
