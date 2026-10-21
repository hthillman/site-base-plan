-- Supabase: saved plans (created 2026-10-20 through the deployment; kept here for reference)
create table if not exists public.plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  run_id text not null,
  title text not null default 'Site plan',
  state text not null default '',
  files jsonb not null default '{}'::jsonb,
  saved_at timestamptz not null default now(),
  unique (user_id, run_id)
);
create index if not exists plans_user_saved on public.plans (user_id, saved_at desc);
alter table public.plans enable row level security;
create policy "own plans: read" on public.plans for select to authenticated using (auth.uid() = user_id);
create policy "own plans: delete" on public.plans for delete to authenticated using (auth.uid() = user_id);
