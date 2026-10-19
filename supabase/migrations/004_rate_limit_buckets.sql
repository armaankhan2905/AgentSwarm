-- Apply after 003_deployment_privileges.sql.
-- Request quotas/cooldowns are shared by API workers and must not live only in
-- process memory. This table is server-side operational state, not browser data.
begin;

create table if not exists public.rate_limit_buckets (
    key varchar(255) primary key,
    window_started double precision not null,
    count integer not null default 0 check (count >= 0),
    updated_at varchar(40) not null
);

revoke all on public.rate_limit_buckets from public, anon, authenticated;
grant select, insert, update, delete on public.rate_limit_buckets to service_role;

do $$
begin
    execute format(
        'grant select, insert, update, delete on table public.rate_limit_buckets to %I',
        current_user
    );
end $$;

alter default privileges in schema public revoke all on tables from public, anon, authenticated;

commit;
