-- WorldColony — Supabase schema
-- Run this once in the Supabase SQL editor (or via psql with DIRECT_URL).
--
-- Persistence model:
--   colonies → DB-backed, survives reloads, broadcast via Postgres changes
--   queens   → NOT a table. Live positions ride a Realtime Broadcast channel
--              ("queens") from the browser; nothing is written to disk.
--
-- Auth model: Phantom pubkey is the identity. RLS permits anyone to write
-- their own row. This is fine for a hackathon demo. To harden later, add a
-- Sign-In-with-Solana JWT and use `auth.jwt() ->> 'sub' = pubkey` checks.

-- ---------------------------------------------------------------------
-- colonies: one row per Phantom wallet
-- ---------------------------------------------------------------------
create table if not exists public.colonies (
  pubkey      text primary key,
  angle       double precision not null,
  dist        double precision not null,
  accent      bigint not null,                    -- 0xRRGGBB as integer
  name        text not null,
  founded_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists colonies_updated_at_idx
  on public.colonies (updated_at desc);

-- Bump updated_at on every row update
create or replace function public.colonies_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists colonies_touch_updated_at on public.colonies;
create trigger colonies_touch_updated_at
  before update on public.colonies
  for each row execute function public.colonies_touch_updated_at();

-- ---------------------------------------------------------------------
-- Row-level security: world is publicly readable; any client can write
-- their own row (no auth yet — pubkey is self-declared).
-- ---------------------------------------------------------------------
alter table public.colonies enable row level security;

drop policy if exists "colonies_public_read"   on public.colonies;
drop policy if exists "colonies_public_insert" on public.colonies;
drop policy if exists "colonies_public_update" on public.colonies;

create policy "colonies_public_read"
  on public.colonies for select using (true);

create policy "colonies_public_insert"
  on public.colonies for insert with check (true);

create policy "colonies_public_update"
  on public.colonies for update using (true) with check (true);

-- ---------------------------------------------------------------------
-- Realtime: stream INSERT/UPDATE/DELETE on colonies to subscribed clients
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'colonies'
  ) then
    alter publication supabase_realtime add table public.colonies;
  end if;
end $$;
